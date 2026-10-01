"""깃발대항전 봇 — 입출력 뼈대 (지침서 5.4).

입력은 END까지 바로 끝까지 읽고, 출력은 명령만 stdout에 쓴 뒤 END와 flush.
예외가 나도 프로세스는 죽지 않고 대체 명령을 낸다. 입력이 끝날(EOF) 때까지 종료하지 않는다.
"""
import sys
import time

T_START = time.perf_counter()


def read_block():
    """END까지 읽어 줄 목록을 돌려준다. EOF면 None."""
    lines = []
    while True:
        line = sys.stdin.readline()
        if not line:
            return None
        s = line.strip()
        if s == 'END':
            return lines
        if s:
            lines.append(s)


def safe_fallback(blk):
    """어떤 경우에도 예외를 내지 않는 대체 명령. 실패하면 빈 목록."""
    try:
        res = None
        for s in blk:
            t = s.split()
            if t and t[0] == 'RESOURCE':
                res = int(t[1])
        n = (res or 0) // 3            # 단가 정보가 없으면 3으로 본다
        return [f"SPAWN W {n}"] if n >= 1 else []
    except Exception:
        return []


def main():
    init = read_block()
    if init is None:
        return
    bot = None
    try:
        from bot import Bot
        bot = Bot(init, T_START)
    except Exception as e:
        sys.stderr.write(f"ERR init: {e!r}\n")
        bot = None                     # 초기화가 실패해도 루프는 계속 돈다
    while True:
        blk = read_block()
        if blk is None:
            break                      # 입력이 끝날 때까지 종료하지 않는다 (E-29)
        t0 = time.perf_counter()
        cmds = None
        if bot is not None:
            try:
                cmds = bot.on_turn(blk, t0)
            except Exception as e:
                import traceback
                tb = traceback.extract_tb(e.__traceback__)
                where = f"{tb[-1].filename.rsplit('/', 1)[-1]}:{tb[-1].lineno}" if tb else ''
                sys.stderr.write(f"ERR turn {getattr(bot, 'turn', -1)}: {e!r} @{where}\n")
        if cmds is None:
            cmds = safe_fallback(blk)
        sys.stdout.write('\n'.join(cmds + ['END']) + '\n')
        sys.stdout.flush()


if __name__ == '__main__':
    main()
