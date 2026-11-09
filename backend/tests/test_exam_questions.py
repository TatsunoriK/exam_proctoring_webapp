import unittest
from copy import deepcopy
from app.exam_questions import attempt_questions


class AttemptQuestionsTest(unittest.TestCase):
    def test_random_subset_keeps_correct_answers_and_original_bank(self):
        body = {"questions": [{"text": str(i), "options": ["a", "b", "c", "d"],
                               "correct": i % 4, "image": "image"} for i in range(25)],
                "randomQuestions": True, "questionCount": 10, "shuffleOptions": True}
        original = deepcopy(body)
        selected = attempt_questions(body)
        self.assertEqual(len(selected), 10)
        self.assertEqual(len({q["text"] for q in selected}), 10)
        for q in selected:
            source = original["questions"][int(q["text"])]
            self.assertEqual(q["options"][q["correct"]], source["options"][source["correct"]])
            self.assertEqual(q["image"], "image")
        self.assertEqual(body, original)

    def test_legacy_exams_keep_order_and_do_not_share_mutable_data(self):
        body = {"questions": [{"text": "Q", "options": ["a", "b", "c", "d"], "correct": 2}]}
        selected = attempt_questions(body)
        self.assertEqual(selected, body["questions"])
        selected[0]["options"][0] = "changed"
        self.assertEqual(body["questions"][0]["options"][0], "a")
