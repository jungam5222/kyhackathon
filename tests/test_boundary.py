"""부록 A 경계선 테스트 벡터 (지침서 22.2): 구현한 경계선이 목록과 정확히 같아야 한다.

    python3 tests/test_boundary.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'bot'))

from mapinfo import MapInfo, cell, cx, cy   # noqa: E402
from territory import Territory             # noqa: E402

MAP1 = """...#....#......
..#B....#.....B
....H..B#......
.....BB....#..#
.#........B....
.........#...B.
..............#
..B....B....B..
#..............
.B...#.........
....B........#.
#..#....BB.....
......#B..H....
B.....#....B#..
......#....#...""".split()

MAP2 = """......#........
.#.+...#...L...
..sY#..........
...#.......h.#.
...#.....W.#.#.
...............
...#....D....E.
......sPs......
.E....D....#...
...............
.#.#.W.....#...
.#.h.......#...
..........#Ks..
...L...#...+.#.
........#......""".split()

MAP3 = """.............#.
..#........hE.#
..##.D.........
.#Y.....s...+..
.............#.
...#s#...W....#
..L............
.......P.......
............L..
#....W...#s#...
.#.............
..+...s.....K#.
.........D.##..
#.Eh........#..
.#.............""".split()


def to_rule_map(rows):
    out = []
    for r in rows:
        r = r.replace('Y', 'H').replace('K', 'H')
        r = ''.join('B' if ch not in '.#H' else ch for ch in r)
        out.append(r)
    return out


def make(rows, base_y, base_k, team):
    rows = to_rule_map(rows)
    lines = ['INIT 15 15', f'TEAM {team}'] + [f'MAP {r}' for r in rows]
    blds = [(x, y) for y in range(15) for x in range(15) if rows[y][x] == 'B']
    lines.append(f'BUILDINGS {len(blds)}')
    for i, (x, y) in enumerate(blds):
        lines.append(f'{i} {x} {y} LIBRARY')
    lines += [f'BASE Y {base_y[0]} {base_y[1]}', f'BASE K {base_k[0]} {base_k[1]}']
    return MapInfo(lines)


def boundary(mp, L):
    terr = Territory(mp)
    excl = set(mp.closed[mp.base_e])
    _, F, _ = terr.region([L] * mp.nsec, excl, [mp.base_us], [])
    return sorted(F)


def parse(s):
    out = []
    for tok in s.replace(') (', ');(').split(';'):
        x, y = tok.strip('() ').split(',')
        out.append(cell(int(x), int(y)))
    return sorted(out)


CASES = [
    (MAP1, (4, 2), (10, 12), 'K', -2, 13, "(10,5) (11,5) (12,5) (13,5) (14,5) (9,6) (8,7) (7,8) (6,9) (5,10) (4,11) (1,12) (2,12)"),
    (MAP1, (4, 2), (10, 12), 'K', 0, 11, "(12,3) (13,3) (10,4) (8,6) (7,7) (6,8) (0,10) (1,10) (2,10) (3,10) (4,10)"),
    (MAP1, (4, 2), (10, 12), 'K', 2, 13, "(10,0) (10,1) (10,2) (10,3) (9,4) (8,5) (7,6) (6,7) (5,8) (1,9) (2,9) (3,9) (4,9)"),
    (MAP1, (4, 2), (10, 12), 'Y', -2, 13, "(12,2) (13,2) (10,3) (9,4) (8,5) (7,6) (6,7) (5,8) (0,9) (1,9) (2,9) (3,9) (4,9)"),
    (MAP1, (4, 2), (10, 12), 'Y', 0, 11, "(10,4) (11,4) (12,4) (13,4) (14,4) (8,6) (7,7) (6,8) (4,10) (1,11) (2,11)"),
    (MAP1, (4, 2), (10, 12), 'Y', 2, 13, "(10,5) (11,5) (12,5) (13,5) (9,6) (8,7) (7,8) (6,9) (5,10) (4,11) (4,12) (4,13) (4,14)"),
    (MAP2, (3, 2), (11, 12), 'K', -2, 12, "(12,3) (14,3) (10,5) (9,6) (8,7) (7,8) (6,9) (5,10) (4,11) (3,12) (3,13) (3,14)"),
    (MAP2, (3, 2), (11, 12), 'K', 0, 14, "(12,0) (12,1) (12,2) (11,3) (10,4) (9,5) (8,6) (7,7) (6,8) (5,9) (4,10) (3,11) (0,12) (2,12)"),
    (MAP2, (3, 2), (11, 12), 'K', 2, 12, "(11,0) (11,1) (11,2) (10,3) (9,4) (8,5) (7,6) (6,7) (5,8) (4,9) (0,11) (2,11)"),
    (MAP3, (2, 3), (12, 11), 'K', -2, 15, "(12,0) (12,1) (12,2) (12,3) (11,4) (10,5) (9,6) (8,7) (7,8) (6,9) (5,10) (4,11) (4,12) (4,13) (4,14)"),
    (MAP3, (2, 3), (12, 11), 'K', 0, 15, "(11,0) (11,1) (11,2) (11,3) (10,4) (9,5) (8,6) (7,7) (6,8) (5,9) (4,10) (3,11) (3,12) (3,13) (3,14)"),
    (MAP3, (2, 3), (12, 11), 'K', 2, 12, "(10,0) (10,1) (10,2) (10,3) (9,4) (8,5) (7,6) (6,7) (5,8) (4,9) (3,10) (2,11)"),
]


class BoundaryTest(unittest.TestCase):
    def test_appendix_a(self):
        for rows, by, bk, team, L, n, expect in CASES:
            with self.subTest(map=id(rows), team=team, L=L):
                mp = make(rows, by, bk, team)
                F = boundary(mp, L)
                exp = parse(expect)
                self.assertEqual(len(exp), n)
                self.assertEqual([(cx(c), cy(c)) for c in F], [(cx(c), cy(c)) for c in exp])

    def test_vertex_cut(self):
        """상대 본진에서 F를 피해 BFS하면 T 안쪽(F 제외)에 닿지 않는다."""
        for rows, by, bk, team, L, n, expect in CASES:
            mp = make(rows, by, bk, team)
            terr = Territory(mp)
            excl = set(mp.closed[mp.base_e])
            T, F, _ = terr.region([L] * mp.nsec, excl, [mp.base_us], [])
            Fs = set(F)
            seen = {mp.base_e}
            stack = [mp.base_e]
            while stack:
                u = stack.pop()
                for v in mp.nbrs[u]:
                    if v in seen or v in Fs:
                        continue
                    seen.add(v)
                    stack.append(v)
            inner = [c for c in mp.cells if T[c] and c not in Fs]
            self.assertFalse(any(c in seen for c in inner))


if __name__ == '__main__':
    unittest.main()
