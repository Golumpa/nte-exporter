KNOWN_REWARDS = {
    "98bdc9ad7d91d5cdd189a5b901": {"type": "arc", "id": "fork_dustbin", "name": "Dangerous Game", "rank": "B"},
    "98bdc9ad7dd9a5b99501": {"type": "arc", "id": "fork_vine", "name": "Be Happy", "rank": "B"},
    "98bdc9ad7db9bdb9bdcd01": {"type": "arc", "id": "fork_nonos", "name": "First Step to Success", "rank": "B"},
    "98bdc9ad7d85c1c1b1a585b98d9501": {"type": "arc", "id": "fork_appliance", "name": "\"Real Music\"", "rank": "B"},
    "98bdc9ad7d41c9bdad85c9e5bdb901": {"type": "arc", "id": "fork_Prokaryon", "name": "Us.", "rank": "B"},
    "98bdc9ad7d4185c195c941b185b99501": {"type": "arc", "id": "fork_PaperPlane", "name": "Clear Skies", "rank": "A"},
    "98bdc9ad7ddda1d585add585b99d01": {"type": "arc", "id": "fork_wuhuakuang", "name": "The Forgotten", "rank": "A"},
    "98bdc9ad7dddd5a1d585add585b99d01": {"type": "arc", "id": "fork_wuhuakuang", "name": "The Forgotten", "rank": "A"},
    "98bdc9ad7d2da5d19501": {"type": "arc", "id": "fork_Kite", "name": "Watch Your Heads!", "rank": "A"},
    "98bdc9ad7de5d5c995b901": {"type": "arc", "id": "fork_yuren", "name": "Umbrella", "rank": "A"},
    "98bdc9ad7de585bd9185bd01": {"type": "arc", "id": "fork_yaodao", "name": "Drawn Blade", "rank": "A"},
    "10a58d9539bdc9b585b101": {"type": "item", "id": "DiceNormal", "name": "Fabricated Dice", "rank": None},
    "10a58d957dd1a58dad95d17dc1c400": {"type": "item", "id": "Dice_ticket_01", "name": "Warp Piece", "rank": None},
    "10a58d957dd1a58dad95d17dc1c800": {"type": "item", "id": "Dice_ticket_02", "name": "Lost Piece", "rank": None},
    "10a58d95b1a5b5a5d19501": {"type": "item", "id": "Dicelimite", "name": "Solid Dice", "rank": None},
    "1885cda1a5bdb97dd995a1a58db1957dc5c0c4c07c59c1c0e000": {
        "type": "cosmetic",
        "id": "Fashion_vehicle_1010_V008",
        "name": "Fashion Vehicle Skin 1010 V008",
        "rank": None,
    },
    "1885cda1a5bdb97d1db1a591957dc5c0c4c000": {
        "type": "cosmetic",
        "id": "Fashion_glide_1010",
        "name": "Fashion Glider 1010",
        "rank": None,
    },
    "c4c0cccc00": {"type": "character", "id": "1033", "name": "Adler", "rank": "A"},
    "c4c0c8c000": {"type": "character", "id": "1020", "name": "Haniel", "rank": "A"},
    "c4c0c8cc00": {"type": "character", "id": "1023", "name": "Baicang", "rank": "S"},
    "c4c0c8d400": {"type": "character", "id": "1025", "name": "Hathor", "rank": "S"},
    "c4c0c4e400": {"type": "character", "id": "1019", "name": "Mint", "rank": "A"},
    "c4c0c0e000": {"type": "character", "id": "1008", "name": "Skia", "rank": "A"},
    "c4c0dcc0": {"type": "character", "id": "1070", "name": "Aurelia", "rank": "A"},
    "c4c0dcc000": {"type": "character", "id": "1070", "name": "Aurelia", "rank": "A"},
    "c4c0c8c4": {"type": "character", "id": "1021", "name": "Edgar", "rank": "A"},
    "c4c0c8c400": {"type": "character", "id": "1021", "name": "Edgar", "rank": "A"},
}

ARC_META = {
    "fork_nonos": {"name": "First Step to Success", "rank": "B"},
    "fork_Prokaryon": {"name": "Us.", "rank": "B"},
    "fork_appliance": {"name": "\"Real Music\"", "rank": "B"},
    "fork_PaperPlane": {"name": "Clear Skies", "rank": "A"},
    "fork_mofeikesi": {"name": "Good Boy's Grand Adventure", "rank": "S"},
    "fork_dustbin": {"name": "Dangerous Game", "rank": "B"},
    "fork_vine": {"name": "Be Happy", "rank": "B"},
    "fork_Kite": {"name": "Watch Your Heads!", "rank": "A"},
    "fork_wuhuakuang": {"name": "The Forgotten", "rank": "A"},
    "fork_jingmotingyuan": {"name": "Camellia Society", "rank": "S"},
    "fork_yuren": {"name": "Umbrella", "rank": "A"},
    "fork_yaodao": {"name": "Drawn Blade", "rank": "A"},
}

CHARACTERS = {
    "1003": {"name": "Sakiri", "rank": "S"},
    "1004": {"name": "Lacrimosa", "rank": "S"},
    "1008": {"name": "Skia", "rank": "A"},
    "1010": {"name": "Nanally", "rank": "S"},
    "1019": {"name": "Mint", "rank": "A"},
    "1020": {"name": "Haniel", "rank": "A"},
    "1021": {"name": "Edgar", "rank": "A"},
    "1023": {"name": "Baicang", "rank": "S"},
    "1025": {"name": "Hathor", "rank": "S"},
    "1033": {"name": "Adler", "rank": "A"},
    "1039": {"name": "Fadia", "rank": "S"},
    "1046": {"name": "Zero", "rank": "S"},
    "1051": {"name": "Zero", "rank": "S"},
    "1052": {"name": "Hotori", "rank": "S"},
    "1054": {"name": "Daffodill", "rank": "S"},
    "1055": {"name": "Jiuyuan", "rank": "S"},
    "1056": {"name": "Lacrimosa", "rank": "S"},
    "1070": {"name": "Aurelia", "rank": "A"},
    "1073": {"name": "Chiz", "rank": "S"},
}


def character_id_to_key(character_id: str) -> str:
    return "".join(f"{0xC0 + int(digit) * 4:02x}" for digit in character_id) + "00"


for _character_id, _info in CHARACTERS.items():
    KNOWN_REWARDS.setdefault(
        character_id_to_key(_character_id),
        {
            "type": "character",
            "id": _character_id,
            "name": _info["name"],
            "rank": _info["rank"],
        },
    )
