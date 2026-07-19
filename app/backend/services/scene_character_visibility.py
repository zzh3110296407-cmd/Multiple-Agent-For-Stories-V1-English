from app.backend.models.character import Character


ROLE_VISIBILITY_ALIASES: dict[str, tuple[str, ...]] = {
    "local_witness": ("local witness", "\u672c\u5730\u89c1\u8bc1\u8005", "\u89c1\u8bc1\u8005"),
    "temporary_guide": ("temporary guide", "local guide", "\u4e34\u65f6\u5411\u5bfc", "\u5411\u5bfc"),
    "case_informant": ("case informant", "informant", "\u7ebf\u4eba", "\u77e5\u60c5\u8005"),
    "minor_opponent": ("minor opponent", "temporary opponent", "\u4e34\u65f6\u5bf9\u624b", "\u5bf9\u624b"),
    "guard_or_gatekeeper": ("guard", "gatekeeper", "\u5b88\u536b", "\u95e8\u536b"),
    "crowd_reaction": ("crowd witness", "crowd", "\u56f4\u89c2\u8005", "\u4eba\u7fa4"),
    "messenger": ("messenger", "\u4fe1\u4f7f", "\u4f20\u4ee4\u8005"),
    "patrol": ("patrol", "\u5de1\u903b\u8005", "\u5de1\u903b\u961f"),
    "driver": ("driver", "\u8f66\u592b", "\u53f8\u673a"),
    "servant": ("servant", "\u4f8d\u4ece", "\u4ec6\u4eba"),
    "shopkeeper": ("shopkeeper", "\u5e97\u4e3b", "\u638c\u67dc"),
}


def character_visibility_aliases(character: Character) -> list[str]:
    aliases = [
        character.character_id,
        character.name,
        character.profile.identity,
    ]
    role_keys = {
        str(character.role or "").strip().casefold(),
        str(character.profile.story_function or "").strip().casefold(),
    }
    for role_key in role_keys:
        aliases.extend(ROLE_VISIBILITY_ALIASES.get(role_key, ()))
    result: list[str] = []
    seen: set[str] = set()
    for alias in aliases:
        clean = str(alias or "").strip()
        folded = clean.casefold()
        if clean and folded not in seen:
            result.append(clean)
            seen.add(folded)
    return result


def text_mentions_character(text: str, character: Character) -> bool:
    haystack = str(text or "").casefold()
    return any(
        alias.casefold() in haystack
        for alias in character_visibility_aliases(character)
    )
