from app.services.text import best_passages, bm25_rank, chunk_text, cited_numbers


def test_chunk_text_respects_size_and_overlap():
    text = " ".join(f"Sentence number {i} is here." for i in range(200))
    chunks = chunk_text(text, size=300, overlap=50)
    assert len(chunks) > 5
    assert all(len(c) <= 300 for c in chunks)
    # overlap means consecutive chunks share some text
    assert chunks[0][-20:].split()[-1] in chunks[1]


def test_chunk_short_text_is_single_chunk():
    assert chunk_text("  hello   world  ") == ["hello world"]
    assert chunk_text("") == []


def test_bm25_prefers_relevant_passage():
    passages = ["cats sleep all day long", "quantum computing uses qubits for computation", "dogs bark"]
    scores = bm25_rank("how do qubits work in quantum computers", passages)
    assert scores.index(max(scores)) == 1


def test_best_passages_keeps_relevant_content():
    filler = "Lorem ipsum dolor sit amet consectetur. " * 60
    key = " Photosynthesis converts light energy into chemical energy. "
    text = "Intro paragraph about the page. " + filler + key + filler
    out = best_passages("what does photosynthesis convert", text, max_chars=700)
    assert "Photosynthesis" in out
    assert out.startswith("Intro")
    assert len(out) <= 800


def test_cited_numbers():
    assert cited_numbers("A [1] and B [2][10], not [x]") == {1, 2, 10}
