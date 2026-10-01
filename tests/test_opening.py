"""오프닝 계획기 회귀 테스트 (지침서 16.5): 맵 2·3, 우리 = K, 기대 점령 턴 ±1.

    python3 tests/test_opening.py
"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from opening_maps import MAP2, MAP3, plan_for   # noqa: E402

# (원래 좌표 x, y, 종류, 기대 턴)
EXPECT = {
    'map2': (MAP2, [(12, 12, 'STATION', 1), (11, 13, 'HOSPITAL', 1), (13, 6, 'ENG', 8),
                    (8, 6, 'DEPOT', 11), (8, 7, 'STATION', 11), (7, 7, 'PLAZA', 12),
                    (3, 11, 'HALL', 12), (11, 3, 'HALL', 13)], 12),
    'map3': (MAP3, [(12, 8, 'LIBRARY', 3), (9, 12, 'DEPOT', 4), (10, 9, 'STATION', 6),
                    (12, 3, 'HOSPITAL', 8), (6, 11, 'STATION', 8), (12, 1, 'ENG', 10),
                    (11, 1, 'HALL', 11), (7, 7, 'PLAZA', 11)], 9),
}


class OpeningTest(unittest.TestCase):
    def test_regression(self):
        for name, (rows, items, tele) in EXPECT.items():
            mp, plan = plan_for(rows, 'K')
            for x, y, kind, t in items:
                with self.subTest(map=name, building=(x, y, kind)):
                    c = (14 - y) * 15 + (14 - x)       # K 진영은 정규 좌표계
                    b = mp.bld_at[c]
                    self.assertEqual(b.kind, kind)
                    self.assertIn(b.i, plan.cap_turn, f"{name} {kind}({x},{y}) 계획에 없음")
                    self.assertLessEqual(abs(plan.cap_turn[b.i] - t), 1)
            with self.subTest(map=name, tele=True):
                self.assertIsNotNone(plan.tele_turn)
                self.assertLessEqual(abs(plan.tele_turn - tele), 1)

    def test_constraints_and_time(self):
        for name, (rows, _, _) in EXPECT.items():
            t0 = time.perf_counter()
            mp, plan = plan_for(rows, 'K')
            self.assertLess(time.perf_counter() - t0, 1.0)
            self.assertIsNotNone(plan._evaluate(plan.lanes))
            seen = set()
            for lane in plan.lanes:
                for bi in lane:
                    self.assertNotIn(bi, seen)       # 한 건물에 깃발 하나
                    seen.add(bi)
                    self.assertNotEqual(mp.blds[bi].side, 'enemy')

    def test_rule_lanes_fallback(self):
        mp, plan = plan_for(MAP3, 'K')
        lanes = plan._repair(plan._rule_lanes())
        self.assertIsNotNone(plan._evaluate(lanes))
        self.assertTrue(any(lanes))


if __name__ == '__main__':
    unittest.main()
