"""The prompts and the tools agree on the 2x2 vocabulary."""


def test_web_prompts_name_the_four_cells_and_never_the_old_slots():
    from lumen_agent import prompts_web

    text = prompts_web.build_web_author_prompt.__doc__ or ""
    # Assert against the SOURCE, not a rendered prompt (rendering needs a full
    # config): the vocabulary must appear in the module.
    import inspect

    source = inspect.getsource(prompts_web)
    for cell in ("light_lockup", "dark_lockup", "light_mark", "dark_mark"):
        assert cell in source
    assert "asset ids per slot" not in source


def test_scene_prompts_name_the_cells():
    import inspect

    from lumen_agent import prompts

    source = inspect.getsource(prompts)
    assert "light_lockup" in source


def test_rendered_web_author_prompt_names_the_cells():
    # D4: the SOURCE assertions above prove the words exist; this proves they REACH the
    # agent. The fetch_logo prose lives inside the ACCOUNT block, which renders only when
    # an `account_card` is passed — so this render passes one.
    from lumen_agent.prompts_web import build_web_author_prompt

    rendered = build_web_author_prompt(
        brand_card="{}", theme_token_names="brand, ink", account_card="{}"
    )
    for cell in ("light_lockup", "dark_lockup", "light_mark", "dark_mark"):
        assert cell in rendered
    assert "asset ids per slot" not in rendered


def test_rendered_web_author_prompt_without_an_account_card_has_no_old_slot_words():
    # The non-ABM render (what `test_web_account_logo_bind.py::_author_prompt` builds)
    # must not carry the retired vocabulary either.
    from lumen_agent.prompts_web import build_web_author_prompt

    rendered = build_web_author_prompt(brand_card="{}", theme_token_names="brand, ink")
    assert "asset ids per slot" not in rendered
