// Conventional commit linting per ~/.claude/rules/commit-standards.md.
// Enforced on PR titles via .github/workflows/ci.yml.

module.exports = {
  extends: ["@commitlint/config-conventional"],
  rules: {
    "type-enum": [
      2,
      "always",
      [
        "feat",
        "fix",
        "docs",
        "style",
        "refactor",
        "test",
        "perf",
        "ci",
        "build",
        "chore",
        "revert",
        "init",
      ],
    ],
    "subject-case": [2, "never", ["pascal-case", "upper-case", "start-case"]],
    "subject-empty": [2, "never"],
    "subject-full-stop": [2, "never", "."],
    // Commit-standards soft-caps at 72; commitlint hard-caps at 120 so
    // long "feat(subsystem): ... a, b, c" summaries for multi-module
    // commits do not fail CI after the fact.
    "header-max-length": [2, "always", 120],
  },
};
