String countLabel(int count, String singular, [String? plural]) =>
    '$count ${count == 1 ? singular : plural ?? '${singular}s'}';
