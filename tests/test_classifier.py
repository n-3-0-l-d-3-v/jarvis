from jarvis.classifier import DEFAULT_AGENT, classify


def test_alfred_keywords():
    result = classify("can you give me a hint for this leetcode problem")
    assert result.agent == "alfred"
    assert "leetcode" in result.matched_keywords or "hint" in result.matched_keywords


def test_alfred_study_keyword():
    result = classify("I want to study for my interview next week")
    assert result.agent == "alfred"


def test_ultron_keywords():
    result = classify("help me reverse engineer this firmware binary")
    assert result.agent == "ultron"


def test_ultron_cve_keyword():
    result = classify("is there a known CVE for this exploit")
    assert result.agent == "ultron"


def test_friday_keywords():
    result = classify("please capture a note about this article I read")
    assert result.agent == "friday"


def test_friday_youtube_keyword():
    result = classify("summarize this youtube video for my wiki")
    assert result.agent == "friday"


def test_no_match_defaults_to_friday():
    result = classify("what's the weather like tomorrow")
    assert result.agent == DEFAULT_AGENT
    assert result.scores["alfred"] == 0
    assert result.scores["ultron"] == 0
    assert result.scores["friday"] == 0


def test_highest_score_wins_on_mixed_text():
    text = "learn learn learn hint study mastery, one small note"
    result = classify(text)
    assert result.agent == "alfred"
    assert result.scores["alfred"] > result.scores["friday"]


def test_tie_break_priority_alfred_over_ultron_over_friday():
    # one keyword each -> tie; alfred should win by priority order
    text = "learn about this exploit and take a note"
    result = classify(text)
    assert result.scores["alfred"] == result.scores["ultron"] == result.scores["friday"] == 1
    assert result.agent == "alfred"


def test_word_boundary_avoids_false_positive_substring():
    # "notebook" should not match the "note" keyword (word-boundary match)
    result = classify("open my notebook app")
    assert result.scores["friday"] == 0
