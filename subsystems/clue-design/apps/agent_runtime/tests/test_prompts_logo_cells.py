"""The prompts and the tools agree on the 2x2 vocabulary."""


def test_web_prompts_name_the_four_cells_and_never_the_old_slots():
    # Assert against the SOURCE, not a rendered prompt (rendering needs a full
    # config): the vocabulary must appear in the module.
    import inspect

    from lumen_agent import prompts_web

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


def test_rendered_web_author_prompt_offers_the_alternatives():
    """The cells stay the default, and the prompt says the alternatives exist."""
    from lumen_agent.prompts_web import build_web_author_prompt

    rendered = build_web_author_prompt(
        brand_card="{}", theme_token_names="brand, ink", account_card="{}"
    )
    assert "`alternatives`" in rendered
    assert "use a cell first" in rendered


def test_rendered_web_author_prompt_without_an_account_card_has_no_old_slot_words():
    # The non-ABM render (what `test_web_account_logo_bind.py::_author_prompt` builds)
    # must not carry the retired vocabulary either.
    from lumen_agent.prompts_web import build_web_author_prompt

    rendered = build_web_author_prompt(brand_card="{}", theme_token_names="brand, ink")
    assert "asset ids per slot" not in rendered


def test_hotlink_guidance_appears_only_with_a_client_id():
    import inspect

    from lumen_agent import prompts_web

    source = inspect.getsource(prompts_web)
    assert "cdn.brandfetch.io" in source
    assert "fallback/transparent" in source
    # the conditional: the block must be guarded on the client id being set
    assert "brandfetch_client_id" in source


def test_rendered_hotlink_block_carries_the_real_cdn_url():
    # The id is interpolated at prompt build; this fake id never leaves the tests.
    from lumen_agent.prompts_web import build_web_author_prompt

    rendered = build_web_author_prompt(
        brand_card="{}", theme_token_names="brand, ink", brandfetch_client_id="1idTESTID"
    )
    assert (
        "https://cdn.brandfetch.io/domain/THEIR-DOMAIN/theme/dark/fallback/"
        "transparent/type/logo?c=1idTESTID" in rendered
    )
    assert "fallback/transparent" in rendered
    # the personalization marker survives f-string escaping as a literal
    assert "{{account.logo}}" in rendered
    # Brandfetch's CDN refuses HeadlessChrome, so our automated renders show the
    # hotlink empty; the caveat must survive the wrap as one contiguous phrase.
    assert "it renders in the editor preview and on the published page" in rendered


def test_rendered_hotlink_block_is_absent_without_a_client_id():
    from lumen_agent.prompts_web import build_web_author_prompt

    omitted = build_web_author_prompt(brand_card="{}", theme_token_names="brand, ink")
    assert "cdn.brandfetch.io" not in omitted

    explicit_none = build_web_author_prompt(
        brand_card="{}", theme_token_names="brand, ink", brandfetch_client_id=None
    )
    assert "cdn.brandfetch.io" not in explicit_none

    # the automated-render caveat belongs to the block, so it goes with it
    caveat = "it renders in the editor preview and on the published page"
    assert caveat not in omitted
    assert caveat not in explicit_none


def test_hotlink_block_and_account_block_render_together():
    from lumen_agent.prompts_web import build_web_author_prompt

    rendered = build_web_author_prompt(
        brand_card="{}",
        theme_token_names="brand, ink",
        account_card="{}",
        brandfetch_client_id="1idTESTID",
    )
    assert "cdn.brandfetch.io" in rendered
    assert "fetch_logo" in rendered
