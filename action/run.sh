#!/usr/bin/env bash
# The testhunch GitHub Action (see action.yml). Every input arrives as an environment variable.
set -euo pipefail

fail() {
  echo "::error title=testhunch::$1"
  exit 1
}

case "${TESTHUNCH_COMMAND}" in
  ingest | prioritize) ;;
  *) fail "the command input must be ingest or prioritize, not '${TESTHUNCH_COMMAND}'" ;;
esac
case "${TESTHUNCH_RECORD}" in
  true) record="--record" ;;
  false) record="" ;;
  *) fail "the record input must be true or false, not '${TESTHUNCH_RECORD}'" ;;
esac

# Run the package from this action's own checkout, so the action and the CLI are one version.
# It is built into a new directory every time: uv reuses a cached build of a source directory
# until pyproject.toml changes, even with --refresh, so older code could otherwise run, e.g. on
# a self-hosted runner that keeps its uv cache.
wheels="$(mktemp -d "${RUNNER_TEMP}/testhunch-wheel-XXXXXX")"
uv build --quiet --wheel --out-dir "${wheels}" "${GITHUB_ACTION_PATH}"
wheel="$(find "${wheels}" -name 'testhunch-*.whl')"
if command -v cygpath > /dev/null; then
  wheel="$(cygpath --mixed "${wheel}")" # Windows runners: uv needs C:/..., not /c/...
fi

testhunch() {
  uvx --quiet --from "testhunch[postgres] @ ${wheel}" testhunch "$@"
}

if [ -n "${TESTHUNCH_INPUT_DATABASE_URL}" ]; then
  export TESTHUNCH_DATABASE_URL="${TESTHUNCH_INPUT_DATABASE_URL}"
fi

base="${TESTHUNCH_BASE}"
if [ -z "${base}" ] && [ -n "${GITHUB_BASE_REF:-}" ]; then
  base="origin/${GITHUB_BASE_REF}"
fi
# Below, ${base:+--base "${base}"} expands to the two words `--base <ref>`, or to nothing.

case "${TESTHUNCH_COMMAND}" in
  ingest)
    reports=()
    while IFS= read -r line; do
      line="${line#"${line%%[![:space:]]*}"}"
      line="${line%"${line##*[![:space:]]}"}"
      if [ -n "${line}" ]; then
        reports+=("${line}")
      fi
    done <<< "${TESTHUNCH_REPORTS}"
    if [ "${#reports[@]}" -eq 0 ]; then
      fail "the ingest command needs the reports input: JUnit XML files or glob patterns"
    fi

    # Patterns are passed quoted: testhunch expands them itself, the same way on every runner.
    if [ -n "${TESTHUNCH_INPUT_API_URL}" ]; then
      # Sent to a hosted testhunch, so there is no local history to summarise here. Shadow mode
      # still records its ranking locally, so it has nothing to compare against: the summary says
      # what happened rather than printing empty tables.
      sent="$(testhunch ingest "${reports[@]}" ${base:+--base "${base}"} \
        --api "${TESTHUNCH_INPUT_API_URL}")"
      echo "${sent}"
      {
        echo "### testhunch"
        echo
        echo "${sent}"
      } >> "${GITHUB_STEP_SUMMARY}"
    else
      testhunch ingest "${reports[@]}" ${base:+--base "${base}"}
      {
        testhunch report --last "${TESTHUNCH_LAST}" --format markdown
        echo
        testhunch shadow --last "${TESTHUNCH_LAST}" --format markdown
      } >> "${GITHUB_STEP_SUMMARY}"
    fi
    ;;

  prioritize)
    out="${RUNNER_TEMP}/testhunch"
    mkdir -p "${out}"
    rank() {
      testhunch prioritize ${base:+--base "${base}"} "$@"
    }
    # Recorded once, with the first of the three identical rankings.
    rank ${record:+"${record}"} --format json > "${out}/ranking.json"
    rank --format keys > "${out}/ranking.txt"
    rank --format markdown --limit "${TESTHUNCH_SUMMARY_LIMIT}" >> "${GITHUB_STEP_SUMMARY}"
    {
      echo "ranking-json=${out}/ranking.json"
      echo "ranking-keys=${out}/ranking.txt"
    } >> "${GITHUB_OUTPUT}"
    ;;
esac
