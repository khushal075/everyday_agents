"""Validate reproducibility, partition integrity, rounding, and invalid inputs."""

import random
import unittest

from everyday_agents.ml.splitting import split_dataset


class SplittingTests(unittest.TestCase):
    def test_defaults_assign_all_rows_exactly_once(self):
        rows = [{"id": i} for i in range(100)]
        original = list(rows)
        split = split_dataset(rows)
        self.assertEqual((len(split.train), len(split.validation), len(split.test)), (80, 10, 10))
        combined = split.train + split.validation + split.test
        self.assertEqual(len(combined), len(rows))
        self.assertEqual({id(row) for row in combined}, {id(row) for row in rows})
        self.assertEqual(rows, original)
        self.assertIsNot(split.train, rows)

    def test_seed_is_repeatable_and_can_change_assignments(self):
        rows = list(range(100))
        self.assertEqual(split_dataset(rows, seed=7), split_dataset(rows, seed=7))
        self.assertNotEqual(split_dataset(rows, seed=7), split_dataset(rows, seed=8))

    def test_global_rng_state_is_not_modified(self):
        before = random.getstate()
        split_dataset(list(range(20)))
        self.assertEqual(random.getstate(), before)

    def test_order_can_be_preserved(self):
        split = split_dataset(list(range(10)), shuffle=False)
        self.assertEqual(split.train, list(range(8)))
        self.assertEqual(split.validation, [8])
        self.assertEqual(split.test, [9])

    def test_rounding_is_deterministic_and_preserves_total(self):
        split = split_dataset(
            list(range(11)), train_fraction=0.5, validation_fraction=0.25,
            test_fraction=0.25, shuffle=False,
        )
        self.assertEqual((len(split.train), len(split.validation), len(split.test)), (5, 3, 3))
        tied = split_dataset(
            list(range(5)), train_fraction=0.4, validation_fraction=0.3,
            test_fraction=0.3, shuffle=False,
        )
        self.assertEqual((len(tied.train), len(tied.validation), len(tied.test)), (2, 2, 1))

    def test_zero_fraction_is_supported(self):
        split = split_dataset(
            [1, 2], train_fraction=0.5, validation_fraction=0,
            test_fraction=0.5, shuffle=False,
        )
        self.assertEqual(split.train, [1])
        self.assertEqual(split.validation, [])
        self.assertEqual(split.test, [2])

    def test_empty_and_too_small_datasets_are_rejected(self):
        for rows in ([], [1], [1, 2]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                split_dataset(rows)

    def test_invalid_fractions_are_rejected(self):
        for train, validation, test in (
            (0.8, 0.1, 0.2), (-0.1, 0.6, 0.5), (1.1, 0, -0.1),
            (float("nan"), 0.1, 0.1), (float("inf"), 0, 0),
        ):
            with self.subTest(fractions=(train, validation, test)), self.assertRaises(ValueError):
                split_dataset(list(range(20)), train_fraction=train,
                              validation_fraction=validation, test_fraction=test)

    def test_invalid_argument_types_are_rejected(self):
        for options in ({"seed": None}, {"seed": True}, {"shuffle": "yes"},
                        {"train_fraction": "0.8"}, {"train_fraction": True}):
            with self.subTest(options=options), self.assertRaises(TypeError):
                split_dataset(list(range(20)), **options)
        with self.assertRaises(TypeError):
            split_dataset("not records")

    def test_duplicate_values_are_preserved_as_separate_rows(self):
        rows = ["same"] * 10
        split = split_dataset(rows)
        self.assertEqual(split.train + split.validation + split.test, rows)


if __name__ == "__main__":
    unittest.main()
