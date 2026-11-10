# Contributing to QuAIA™

Contributions to the current project should be made in the form of GitHub pull requests (PRs). Each pull request must be reviewed by
repository's owner or any of the core contributors. If you need to refer to the reviewer explicitly, just type @ and reviewer's name in 
the comment to the PR.

Pycharm's default Code Formatter is currently being used in this project. The corresponding config has been exported into 
[this XML](code_style/pycharm.xml) for IntelliJ users.

Python code must follow the [Python Development Guidelines](PYTHON_GUIDELINES.md).

Commits should be small and compilable.

In order to start any contribution work, first you need to create a custom branch from the main branch. After your changes are completed, 
merge the main branch into yours before submitting your PR. Any conflicts will have to be resolved in order to achieve this.

Please add unit tests, if possible, for the implemented feature or bug fix, unless you pull request contains no code changes (e.g. docs updates etc.).

We follow the [Contributor Covenant Code of Conduct](https://www.contributor-covenant.org/version/2/1/code_of_conduct/code_of_conduct.md).

## Contributor License Agreement

QuAIA™ is dual-licensed: it is open source under the GNU Affero General Public License v3.0 (AGPL-3.0-only), and it is also
offered under commercial licenses. To make this possible, every contributor must sign the
[QuAIA™ Individual Contributor License Agreement](CLA.md) (CLA) before their first pull request can be merged.

* When you open your first pull request, the CLA assistant bot comments on it with a link. Sign in with your GitHub account and accept
  the agreement; it takes about a minute and covers all your future contributions to this repository and to the
  [test execution agents](https://github.com/partarstu/test-execution-agents).
* You keep the copyright in your contributions. The CLA grants the maintainer a license to them, including the right to license them
  under the AGPL-3.0 and under commercial terms.
* Every contribution that is merged stays publicly available under the AGPL-3.0.
* If you contribute on behalf of your employer, make sure you are allowed to do so before signing.

Pull requests from contributors who have not signed the CLA cannot be merged.