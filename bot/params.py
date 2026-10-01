"""P- 파라미터 (지침서 23장)와 게임 상수.

코드 안에 매직 넘버를 쓰지 않는다. 숫자는 모두 여기서 정한다.
"""

# ---------------------------------------------------------------- 게임 상수 (규칙서)
LAST_TURN = 160
COST = {'F': 5, 'W': 3, 'S': 2}
COST_W_ENG = 2
RES_CAP = 40
BASE_INCOME = 10
HALL_BONUS = 2
DEPOT_BONUS = 15
CAP_COST = 2
CAP_COST_PLAZA = 4
TELE_MAX = 5
TELE_MIN_STATIONS = 2
VALUE_F, VALUE_W, VALUE_S = 5, 3, 2          # 160턴 판정 3순위 병력 환산

# ---------------------------------------------------------------- 깃발 (13장)
FLAG_OPEN = 5
FLAG_OPEN_CONTESTED = 6       # 쟁탈 건물이 3곳 이상인 맵
FLAG_OPEN_CONTESTED_MIN = 3
FLAG_MID = 5
FLAG_FIN_MAX = 14
FLAG_FIN_STEP = 2             # 마감 증원 턴당 인원
FLAG_FIN_EXTRA = 2            # 마감 정원 = 상대 건물 수 + 이 값
FLAG_SWITCH = 1.5
FLAG_STALL = 3
STALL_COOLDOWN = 10
FLAG_MARGIN_CELL = 0
FLAG_MARGIN_OWN = 1
FREE_RAID = True
FREE_RAID_FLAG_R = 3          # 목표 주변 상대 깃발 금지 반경
SCOUT = False
ENG_HOLD = True
RETAKE_MEMORY = 20
OPEN_FLAG_SCHEDULE = ((1, 2), (3, 2), (4, 1))   # (턴, 깃발 수). 6깃발 맵은 4턴 +1

# ---------------------------------------------------------------- 라인 (10장)
L_BASE = -2
L_OPEN_MAX = 2
L_FLOOR = -4
L_STEP = 2
SECTOR_W = 3
SECTOR_SPAN = 21              # ψ 범위 −10.5 ~ +10.5
EXCL_LATCH = 3
LINE_DONE = 0.9
ADV_E1_MAX = 1
ADV_HYST = 2
ADV_COOLDOWN = 3
ADV_PER_TURN = 1
ADV_SITE_GAP = 2              # 새 경계 칸과 상대 생산지 최소 거리
RET_OCCUPY = 2
RET_UNDERMAN = 3
RET_HYST = 2

# ---------------------------------------------------------------- 슬롯 (11장)
GUARD_HORIZON = 4
GUARD_RELEASE = 6
SITE_FLAG_RADIUS = 2
LAST_STAND_BUILDINGS = 2      # 우리 건물이 이 수 이하이면 P0a
SCREEN = 1
INTERCEPT_RADIUS = 2
INTERCEPT_RELEASE = 4
INTERCEPT_NEED = 2
SCREEN_DEADLINE_R = 4         # 상대 깃발이 이 거리 안이면 P1c
PRESS_MAX = 8
PRESS_HYST = 2
PRESS_PERIOD = 2
SUPPORT_MAX = 2
SLOT_TTL = 2
SCREEN2_RELEASE = 2
GROUP_STALL = 3
SWITCH_COST = 1
DETOUR_MAX = 2
TRADE_LEAD = 5
HUNT_NEW_FLAG_R = 2           # 역행 예외: 새 상대 깃발 거리

# ---------------------------------------------------------------- 모드 (9·18장)
DP_EPS = 0.5
MODE_HYST = 2
FIN_MIN_LEAD = 10
FIN_ENEMY_W = 15
FIN_RATIO = 3.0
FIN_TURN = 110
FIN_LEAD = 20
FIN_MIN_DWELL = 5
FIN_EXIT_TURNS = 2
FIN_MAJ_TURNS = 3
FIN_BREAK_LEAD = -5
FIN_ALL_IN = 2                # 상대 건물이 이 수 이하이면 전원 투입
ENDGAME_TURN = 150

# ---------------------------------------------------------------- 사냥 (11.4)
HUNT_P_BLD = 0.9
HUNT_P_STAY = 0.7
HUNT_P_NEXT = 0.6
HUNT_P_STAY_MOVING = 0.2
HUNT_P_NEXT_STAYING = 0.2
HUNT_COVER_MIN_P = 0.2
HUNT_V_BASE = 5
HUNT_V_LURK = 10
HUNT_V_ONBLD = 20
HUNT_V_ESCORT = 8
HUNT_MAX_CELLS = 2
LURK_RADIUS = 3
LURK_STATIONARY = 3

# ---------------------------------------------------------------- TELE (15장)
TELE_MIN_SAVE = 2
TELE_FLAG_SAVE = 4

# ---------------------------------------------------------------- 분대 (17장)
SQUAD_MIN_VALUE = 5
SQUAD_LAMBDA = 2
SQUAD_WAIT_MAX = 8
SQUAD_MOVE_SLACK = 6          # MOVE 상한 = 대기 칸까지 거리 + 이 값
SQUAD_MAX = 3                 # 동시 분대 상한 (실제로는 여유 병력이 제한한다, 17.1)
SQUAD_MAX_FIN = 4
PH3_TURN = 45                 # PH3 운영 단계 시작 (4.1)
SQUAD_RESERVE = 5             # 분대 병력 산정 시 P0~P2 몫으로 남기는 여유
SQUAD_FWD_HOSP_R = 6
SQUAD_V_FWD_HOSP = 10
SQUAD_V_STATION = 8
SQUAD_UNSAFE_TURNS = 2
DIV_ENG = 6                   # 17.1 가치 식의 6 (공학관 = 생산 +50% 환산)

# ---------------------------------------------------------------- 가치 (16.3·17.1)
VALUE_HORIZON = 40
OPEN_HORIZON_TURN = 30        # 오프닝 계획이 보는 최대 도착 턴
OPEN_VALUE = {
    'ENG1': 12, 'ENG2_BASE': 4, 'HALL': 7, 'DEPOT': 6,
    'STATION2': 4, 'STATION_SRC': 3, 'HOSP_FWD': 4, 'HOSP': 1,
    'PLAZA_BONUS': 1, 'LIBRARY': 2, 'WATCH_BASE': 1, 'WATCH_INFO': 1,
    'OTHER_MULT': 0.5,
}
HOSP_FWD_GAIN = 3             # 본진보다 전선에 이만큼 가까우면 전방 병원
OPEN_ESCORT_FIRST_W_TURN = 2  # 오프닝 전투병 생산 시작 턴
OPEN_LATE_SLACK = 2           # 늦은 쟁탈: t_E보다 이만큼 늦게까지 (호위 동행)
OPEN_LATE_MULT = 0.6          # 늦은 쟁탈 가치 배수
OPEN_CAP_PER_TURN = 4         # 같은 턴 점령 건수 상한 (점령 자금)
SCORE_EST_SIDE = 1.5
SCORE_EST_CENTRAL = 3
SCORE_UB_SIDE = 2
SCORE_UB_CENTRAL = 4
SCORE_PLAZA = 3
FLAG_FUNC_BONUS = {'ENG': 6, 'HALL': 3, 'DEPOT': 1, 'HOSPITAL': 0.8,
                   'LIBRARY': 0.5, 'STATION': 0.3, 'WATCH': 0.2, 'PLAZA': 0}
ENEMY_OWNED_MULT = 1.7        # 상대 소유 건물 가치 배수 (깃발 목표 점수)

# ---------------------------------------------------------------- 시간 (5.3)
OPEN_TIME_S = 0.8
TIME_BUDGET_MS = 150
TIME_HARD_MS = 220
IMPROVE_PASSES = 3
IMPROVE_MAX_GROUPS = 40

# ---------------------------------------------------------------- 로그 (21장)
LOG_LINE_MAX = 300
