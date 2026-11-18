// The shell reports a startup failure as #error=<message> (see lib.rs).
function showError() {
  const match = /(?:^|&)error=([^&]*)/.exec(location.hash.slice(1));
  if (!match) return;
  document.getElementById("starting").hidden = true;
  document.getElementById("failed").hidden = false;
  document.getElementById("error").textContent = decodeURIComponent(match[1]);
}
window.addEventListener("hashchange", showError);
showError();
