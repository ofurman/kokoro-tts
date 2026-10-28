from kokoro_mcp.engine import split_sentences


def test_splits_on_sentence_punctuation():
    assert split_sentences("One. Two! Three?") == ["One.", "Two!", "Three?"]


def test_keeps_closing_quotes_with_their_sentence():
    assert split_sentences('He said "Go." Then left.') == ['He said "Go."', "Then left."]


def test_splits_paragraphs_without_punctuation():
    assert split_sentences("First line\n\nSecond line") == ["First line", "Second line"]


def test_decimal_point_is_not_a_sentence_boundary():
    assert split_sentences("Pi is 3.14 today.") == ["Pi is 3.14 today."]


def test_empty_text_yields_no_chunks():
    assert split_sentences("  \n ") == []


def test_only_whitespace_is_lost():
    text = "Alpha beta. Gamma delta!\n\nEpsilon."
    compact = "".join(split_sentences(text)).replace(" ", "")
    assert compact == text.replace(" ", "").replace("\n", "")
