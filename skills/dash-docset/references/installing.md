# Finding, installing and managing docsets

Read this before `sources`, `install`, `update` or `remove`, or when a
download or source list fails.

- Find a docset with `sources QUERY` (matches names, titles and keywords),
  then `install NAME` (several at once is fine).
- Prefix names when you can (`kapeli:Name`, `user:Name`, `cheat:Name`); a
  prefix is required when sources share a name. A not-found error suggests
  close names and the other prefixes.
- Official names match Dash's feed files (`kapeli:Python`, `kapeli:NodeJS`,
  `kapeli:Django`) or Zeal's names (`kapeli:Python_3`, `kapeli:Python_2`).
  `kapeli:Python` is the newest Python; `kapeli:Python_3` is the same feed
  limited to 3.x (and `Python_2` to 2.x), so `update` never crosses that
  line.
- Pin an older official version with `@`: `kapeli:Python@3.12` installs the
  newest 3.12.x and `update` keeps the pin.
- Cheat sheets are short (Git's has 81 entries); prefer a full docset when
  one exists. Git is only a cheat sheet (`cheat:Git`).
- A docset's name for `-d` and REFs is the one `install` and `list` print,
  which can differ from the source name (`user:Arm Morello A64 ISA`
  installs as `arm64morello`).
- Source lists are cached for a week; `sources --refresh` re-checks them.
  A "note (no action needed)" on stderr says a list came from a fallback
  source because another was unreachable; results are complete.
- If the network only reaches allowed hosts (a sandbox, a corporate proxy, a
  cloud agent environment) and downloads or source lists fail (exit 7),
  give the user [../assets/allowlist.txt](../assets/allowlist.txt): the
  hosts to allow.
- Manage: `list` shows installed docsets and versions, `update [NAME]`
  refreshes one or all, `remove NAME` deletes one (notes are kept).
- `fts` builds a docset's text index on first use (seconds for large
  docsets); `index-text NAME` builds it ahead of time, e.g. right after
  installing.
