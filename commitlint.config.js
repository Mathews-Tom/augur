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
    "header-max-length": [2, "always", 100],
  },
};
