"""Tests for the hermes_cli models module."""

from hermes_cli.models import ANTHROPIC_MODELS, LOCAL_MODELS, menu_labels, model_ids


class TestModelIds:
    def test_returns_non_empty_list(self):
        ids = model_ids()
        assert isinstance(ids, list)
        assert len(ids) > 0

    def test_ids_match_models_list(self):
        ids = model_ids()
        expected = [mid for mid, _ in ANTHROPIC_MODELS + LOCAL_MODELS]
        assert ids == expected

    def test_no_duplicate_ids(self):
        ids = model_ids()
        assert len(ids) == len(set(ids)), "Duplicate model IDs found"


class TestMenuLabels:
    def test_same_length_as_model_ids(self):
        assert len(menu_labels()) == len(model_ids())

    def test_first_label_marked_recommended(self):
        labels = menu_labels()
        assert "recommended" in labels[0].lower()

    def test_each_label_contains_its_model_id(self):
        for label, mid in zip(menu_labels(), model_ids()):
            assert mid in label, f"Label '{label}' doesn't contain model ID '{mid}'"


class TestAnthropicModels:
    def test_structure_is_list_of_tuples(self):
        for entry in ANTHROPIC_MODELS:
            assert isinstance(entry, tuple) and len(entry) == 2
            mid, desc = entry
            assert isinstance(mid, str) and len(mid) > 0
            assert isinstance(desc, str)

    def test_at_least_one_model(self):
        assert len(ANTHROPIC_MODELS) >= 1
