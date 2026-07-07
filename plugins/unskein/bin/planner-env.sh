# UnSkein PLANNER 인증 로드 — source 우선, cwd 폴백 (ADR-0021)
#
# 이 파일은 **source** 한다:  . "${CLAUDE_PLUGIN_ROOT}/bin/planner-env.sh"
# 목적: 플래너 스킬(unskein-scope·unskein-wbs·unskein-drawio·unskein-doctor)이
#       UNSKEIN_API + UNSKEIN_PLANNER_TOKEN(kind=planner) 을 **프로젝트별로 격리된**
#       planner.env 에서 일관되게 로드한다. 여러 프로젝트를 한 플래너로 다룰 때
#       프로젝트마다 자기 토큰·서버가 안 섞이게 하는 것이 취지다.
#
# 해석 순서 (먼저 성립하는 데서 멈춘다 — fallback 금지: 아무 데도 없으면 빈 채로 두고
#            호출 스킬이 "토큰 없음"으로 멈춘다. 조용히 다른 토큰으로 넘어가지 않는다):
#   0) 이미 셸 env 에 UNSKEIN_PLANNER_TOKEN 이 있으면 그대로  ← 명시적 source 존중(우선)
#   1) UNSKEIN_HOME 이 설정됐으면            $UNSKEIN_HOME/planner.env   (실행기 ADR-0020 과 동일 축)
#   2) (폴백) cwd 에서 위로 올라가며 첫       <dir>/.unskein/planner.env  (프로젝트 디렉토리 자동인식)
#   3) 전역                                   ~/.unskein/planner.env      (단일 프로젝트/하위호환)
#
# 왜 이 순서인가: 실행기(EXECUTOR)는 장수 데몬이라 cwd 가 persist 되지 않아 cwd 앵커를
#   기각했다(ADR-0020). 플래너는 대화형 세션이라 cwd 가 안정적이므로 cwd 폴백을 **더한다**.
#   단, 명시적 source(0·1)를 늘 우선해 실행기와 같은 원칙을 기본으로 둔다.
#
# 로드한 파일은 set -a 로 export 해 자식(curl)에 상속시킨다 — planner.env 가 export 를
# 안 붙였어도 안전하게 넘어간다.

_unskein_load_planner_env() {
  # 0) 이미 로드돼 있으면(명시적 source·bashrc) 존중하고 끝 — 재정의하지 않는다.
  if [ -n "${UNSKEIN_PLANNER_TOKEN:-}" ]; then
    UNSKEIN_PLANNER_ENV_FILE="${UNSKEIN_PLANNER_ENV_FILE:-(shell env)}"
    return 0
  fi

  _f=""
  # 1) UNSKEIN_HOME 명시 (실행기와 같은 상태 루트 축)
  if [ -n "${UNSKEIN_HOME:-}" ] && [ -f "${UNSKEIN_HOME}/planner.env" ]; then
    _f="${UNSKEIN_HOME}/planner.env"
  else
    # 2) cwd 폴백 — 현재 디렉토리에서 루트까지 올라가며 첫 .unskein/planner.env
    _d="$PWD"
    while [ -n "$_d" ] && [ "$_d" != "/" ]; do
      if [ -f "${_d}/.unskein/planner.env" ]; then
        _f="${_d}/.unskein/planner.env"
        break
      fi
      _parent="$(dirname "$_d")"
      [ "$_parent" = "$_d" ] && break   # 상대·퇴화 PWD 무한루프 방지 (run_once.py 형제와 동일)
      _d="$_parent"
    done
    # 3) 전역 (단일 프로젝트/하위호환)
    if [ -z "$_f" ] && [ -f "${HOME}/.unskein/planner.env" ]; then
      _f="${HOME}/.unskein/planner.env"
    fi
  fi

  if [ -n "$_f" ]; then
    set -a
    # shellcheck disable=SC1090
    . "$_f"
    set +a
    UNSKEIN_PLANNER_ENV_FILE="$_f"   # 진단용 — 어느 파일에서 로드했는지
  fi
  unset _f _d _parent
}

_unskein_load_planner_env
