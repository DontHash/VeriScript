//! VeriScript desktop shell.
//!
//! The window first shows a bundled splash (`desktop/ui`). Meanwhile the
//! shell starts the local VeriScript server on a free 127.0.0.1 port with a
//! per-launch secret, waits for `/api/health`, then opens the studio through
//! `/__desktop/session`, which exchanges the secret for an HttpOnly cookie.
//! Nothing listens on a public interface and nothing leaves the machine.
//!
//! Server resolution:
//!   1. the bundled sidecar `veriscript-server[.exe]` next to this executable
//!      (release builds; see `desktop/scripts/build_sidecar.py`);
//!   2. otherwise `python webapp/server.py` from this repository checkout
//!      (development). `VERISCRIPT_DESKTOP_PYTHON` picks the interpreter.

use std::io::{Read, Write};
use std::net::{SocketAddr, TcpListener, TcpStream};
use std::path::Path;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use tauri::webview::NewWindowResponse;
use tauri::{Manager, RunEvent, Url, WebviewUrl, WebviewWindowBuilder};

/// First start may download nothing but still loads the OCR models.
const STARTUP_TIMEOUT: Duration = Duration::from_secs(180);
const SERVER_EXE: &str = "veriscript-server";

/// The running server, killed when the app exits.
struct Server(Mutex<Option<Child>>);

pub fn run() {
    let app = tauri::Builder::default()
        .manage(Server(Mutex::new(None)))
        .setup(|app| {
            let port = free_port()?;
            let token = new_token()?;
            let origin = format!("http://127.0.0.1:{port}");

            let nav_origin = origin.clone();
            let popup_origin = origin.clone();
            let window = WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
                .title("VeriScript")
                .inner_size(1280.0, 860.0)
                .min_inner_size(720.0, 560.0)
                .center()
                // Let the page's own HTML5 drop zone receive dropped files.
                .disable_drag_drop_handler()
                .on_navigation(move |url| allow_navigation(url, &nav_origin))
                .on_new_window(move |url, _features| {
                    if same_origin(&url, &popup_origin) {
                        NewWindowResponse::Allow
                    } else {
                        open_external(&url);
                        NewWindowResponse::Deny
                    }
                })
                .build()?;

            let runs_dir = app.path().app_data_dir()?.join("runs");
            std::fs::create_dir_all(&runs_dir)?;
            let log_dir = app.path().app_log_dir()?;
            std::fs::create_dir_all(&log_dir)?;
            let log_path = log_dir.join("server.log");
            let child = spawn_server(port, &token, &runs_dir, &log_path)?;
            *app.state::<Server>().0.lock().unwrap() = Some(child);

            let handle = app.handle().clone();
            std::thread::spawn(move || {
                match wait_until_healthy(port, &token, &handle, &log_path) {
                    Ok(()) => {
                        let url = format!("{origin}/__desktop/session?token={token}");
                        if let Ok(url) = Url::parse(&url) {
                            let _ = window.navigate(url);
                        }
                    }
                    Err(message) => show_error(&window, &message),
                }
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building the VeriScript desktop app");

    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            if let Some(mut child) = handle.state::<Server>().0.lock().unwrap().take() {
                let _ = child.kill();
                let _ = child.wait();
            }
        }
    });
}

// ---------------------------------------------------------------- server --

fn free_port() -> std::io::Result<u16> {
    let listener = TcpListener::bind("127.0.0.1:0")?;
    Ok(listener.local_addr()?.port())
}

/// 32 random bytes, hex-encoded (64 characters).
fn new_token() -> Result<String, Box<dyn std::error::Error>> {
    let mut bytes = [0u8; 32];
    getrandom::fill(&mut bytes).map_err(|e| format!("no system randomness: {e}"))?;
    Ok(bytes.iter().map(|b| format!("{b:02x}")).collect())
}

fn server_command() -> Command {
    let exe_name = format!("{SERVER_EXE}{}", std::env::consts::EXE_SUFFIX);
    if let Some(sidecar) = std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(|dir| dir.join(&exe_name)))
        .filter(|p| p.is_file())
    {
        return Command::new(sidecar);
    }
    let python = std::env::var("VERISCRIPT_DESKTOP_PYTHON")
        .unwrap_or_else(|_| if cfg!(windows) { "python" } else { "python3" }.to_string());
    let script = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../webapp/server.py");
    let mut command = Command::new(python);
    command.arg(script);
    command
}

fn spawn_server(port: u16, token: &str, runs_dir: &Path, log: &Path) -> std::io::Result<Child> {
    // The server's own output goes to a log file (truncated each launch) so
    // a failed start can be diagnosed without a console window.
    let log_file = std::fs::File::create(log)?;
    let mut command = server_command();
    command
        .env("VERISCRIPT_WEB_MODE", "local")
        .env("VERISCRIPT_WEB_HOST", "127.0.0.1")
        .env("VERISCRIPT_WEB_PORT", port.to_string())
        .env("VERISCRIPT_WEB_DESKTOP_TOKEN", token)
        .env("VERISCRIPT_WEB_RUNS_DIR", runs_dir)
        // One person on their own machine: no demo quotas.
        .env("VERISCRIPT_WEB_RATE_MAX", "100000")
        .env("VERISCRIPT_WEB_DAILY_RUNS", "0")
        .env("VERISCRIPT_WEB_DAILY_PAGES", "0")
        .env("VERISCRIPT_WEB_DAILY_PAGES_PER_CLIENT", "0")
        // Uploads stream to disk, so size is not a memory risk here. A
        // 150-page phone bundle (B4) is about 270 MB.
        .env("VERISCRIPT_WEB_MAX_UPLOAD_MB", "2048")
        // Long PDFs run as background jobs with progress and Cancel, so
        // neither a page cap nor a run timeout applies on the desktop.
        .env("VERISCRIPT_WEB_PAGE_CAP", "0")
        .env("VERISCRIPT_WEB_TIMEOUT_S", "0")
        .env("VERISCRIPT_WEB_MAX_QUEUED", "200")
        // Results are kept until the user deletes them: the app-data folder
        // is the user's own disk (TTL 0 = keep).
        .env("VERISCRIPT_WEB_TTL_MINUTES", "0")
        .env("PYTHONUNBUFFERED", "1")
        .env("PYTHONIOENCODING", "utf-8")
        .stdin(Stdio::null())
        .stdout(Stdio::from(log_file.try_clone()?))
        .stderr(Stdio::from(log_file));
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        command.creation_flags(CREATE_NO_WINDOW);
    }
    let child = command.spawn()?;
    #[cfg(windows)]
    kill_with_this_process(&child);
    Ok(child)
}

/// If the shell crashes, Windows still stops the server (job object with
/// KILL_ON_JOB_CLOSE; the handle is closed by the OS when we exit).
#[cfg(windows)]
fn kill_with_this_process(child: &Child) {
    use std::os::windows::io::AsRawHandle;
    use windows_sys::Win32::System::JobObjects::{
        AssignProcessToJobObject, CreateJobObjectW, JobObjectExtendedLimitInformation,
        SetInformationJobObject, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    };
    // SAFETY: plain Win32 calls on handles we own; the info struct is
    // zero-initialised (valid for this POD type) and sized correctly.
    unsafe {
        let job = CreateJobObjectW(std::ptr::null(), std::ptr::null());
        if job.is_null() {
            return;
        }
        let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        let ok = SetInformationJobObject(
            job,
            JobObjectExtendedLimitInformation,
            &info as *const _ as *const core::ffi::c_void,
            std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
        );
        if ok != 0 {
            AssignProcessToJobObject(job, child.as_raw_handle() as _);
        }
        // `job` is intentionally never closed: it must live as long as we do.
    }
}

fn wait_until_healthy(
    port: u16,
    token: &str,
    app: &tauri::AppHandle,
    log: &Path,
) -> Result<(), String> {
    let started = Instant::now();
    while started.elapsed() < STARTUP_TIMEOUT {
        // Scope the lock: holding it across the loop would block app exit.
        let exited = {
            let server = app.state::<Server>();
            let mut guard = server.0.lock().unwrap();
            match guard.as_mut().map(|child| child.try_wait()) {
                Some(Ok(Some(status))) => Some(status),
                _ => None,
            }
        };
        if let Some(status) = exited {
            return Err(format!(
                "The VeriScript engine stopped while starting ({status}). \
                 Details are in {}.",
                log.display()
            ));
        }
        if health_ok(port, token) {
            return Ok(());
        }
        std::thread::sleep(Duration::from_millis(400));
    }
    Err(format!(
        "The VeriScript engine did not start within 3 minutes. Close the app and try again. \
         Details are in {}.",
        log.display()
    ))
}

/// Minimal HTTP/1.1 GET so the shell needs no HTTP client dependency.
fn health_ok(port: u16, token: &str) -> bool {
    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    let Ok(mut stream) = TcpStream::connect_timeout(&addr, Duration::from_millis(500)) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_secs(5)));
    let request = format!(
        "GET /api/health HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n\
         X-VeriScript-Token: {token}\r\nConnection: close\r\n\r\n"
    );
    if stream.write_all(request.as_bytes()).is_err() {
        return false;
    }
    let mut head = [0u8; 16];
    matches!(stream.read(&mut head), Ok(n) if n >= 12 && &head[9..12] == b"200")
}

// ------------------------------------------------------------ navigation --

fn same_origin(url: &Url, origin: &str) -> bool {
    url.origin().ascii_serialization() == origin
}

/// The window may show the bundled splash and the local studio only.
/// Other web links open in the default browser instead.
fn allow_navigation(url: &Url, origin: &str) -> bool {
    if same_origin(url, origin) {
        return true;
    }
    let bundled = matches!(url.scheme(), "tauri")
        || matches!(url.host_str(), Some("tauri.localhost"));
    if bundled {
        return true;
    }
    open_external(url);
    false
}

fn open_external(url: &Url) {
    if !matches!(url.scheme(), "http" | "https" | "mailto") {
        return;
    }
    let target = url.as_str();
    #[cfg(windows)]
    let result = Command::new("rundll32")
        .args(["url.dll,FileProtocolHandler", target])
        .spawn();
    #[cfg(target_os = "macos")]
    let result = Command::new("open").arg(target).spawn();
    #[cfg(all(unix, not(target_os = "macos")))]
    let result = Command::new("xdg-open").arg(target).spawn();
    let _ = result;
}

fn show_error(window: &tauri::WebviewWindow, message: &str) {
    if let Ok(mut url) = window.url() {
        url.set_fragment(Some(&format!("error={}", percent_encode(message))));
        let _ = window.navigate(url);
    }
}

/// Percent-encode everything except RFC 3986 unreserved characters.
fn percent_encode(text: &str) -> String {
    text.bytes()
        .map(|b| match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'.' | b'_' | b'~' => {
                (b as char).to_string()
            }
            _ => format!("%{b:02X}"),
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn tokens_are_64_hex_characters_and_unique() {
        let a = new_token().unwrap();
        let b = new_token().unwrap();
        assert_eq!(a.len(), 64);
        assert!(a.chars().all(|c| c.is_ascii_hexdigit()));
        assert_ne!(a, b);
    }

    #[test]
    fn only_the_local_studio_and_the_splash_may_load_in_the_window() {
        let origin = "http://127.0.0.1:4321";
        let ok = |u: &str| same_origin(&Url::parse(u).unwrap(), origin);
        assert!(ok("http://127.0.0.1:4321/studio"));
        assert!(!ok("http://127.0.0.1:4322/studio"));
        assert!(!ok("http://localhost:4321/studio"));
        assert!(!ok("https://127.0.0.1:4321/studio"));
        assert!(allow_navigation(&Url::parse("http://tauri.localhost/index.html").unwrap(), origin));
        assert!(allow_navigation(&Url::parse("tauri://localhost/index.html").unwrap(), origin));
        // not http(s): refused and not opened
        assert!(!allow_navigation(&Url::parse("file:///C:/Windows/").unwrap(), origin));
    }

    #[test]
    fn percent_encoding_keeps_messages_intact() {
        assert_eq!(percent_encode("a b/é"), "a%20b%2F%C3%A9");
    }

    #[test]
    fn free_ports_are_loopback_and_nonzero() {
        assert_ne!(free_port().unwrap(), 0);
    }
}
