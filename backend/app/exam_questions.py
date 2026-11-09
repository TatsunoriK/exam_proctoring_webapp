"""Build a stable, privately stored question set for each attempt."""
from copy import deepcopy
from random import SystemRandom


def attempt_questions(body):
    rng = SystemRandom()
    questions = deepcopy(body["questions"])
    count = body.get("questionCount", len(questions))
    if body.get("randomQuestions"):
        questions = rng.sample(questions, count)
    if body.get("shuffleOptions"):
        for question in questions:
            order = list(range(len(question["options"])))
            rng.shuffle(order)
            question["options"] = [question["options"][i] for i in order]
            question["correct"] = order.index(question["correct"])
    return questions
