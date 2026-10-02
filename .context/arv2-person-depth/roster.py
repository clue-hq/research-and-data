"""The 10 committee people from the cluehq.ai smoke test. Identity is ALREADY LOCKED
(LinkedIn URLs + same-name exclusions come from .context/arv2-smoke-cluehq/) — this run
does not re-buy identity. Vendelux is skipped (disqualified competitor)."""

import json
import os

PEOPLE = [
    {
        "key": "vari_kaur", "name": "Vari Kaur",
        "aliases": ["Varinder Kaur"],
        "title": "Head of Growth Marketing", "company": "Zafran Security",
        "domain": "zafran.io", "account": "zafran",
        "linkedin": "https://www.linkedin.com/in/varinderkaur",
        "location": "Easton, Pennsylvania, United States",
        "persona": "champion",
        "exclusions": (
            "Vari Kaur, Office and Accounts Administrator at Etherington, Perth Australia "
            "(linkedin.com/in/vari-kaur-95a176102); Varinder Kaur, Digital Marketing Intern at "
            "Webcooks Technologies, Brampton Canada (linkedin.com/in/varinder-kaur-digitalmarketer); "
            "Varinder Kaur, Founder & Content Marketing Strategist at Kaur Realtor Brands "
            "(linkedin.com/in/varinderkaur001); Varinder Kaur, SEO Engineer in Mohali India "
            "(linkedin.com/in/varinder-kaur-237b69121). None of those are the subject."),
        "known_history": "Secureworks, ReSource Pro, Axiom, Tangoe, Ivanti, Grazitti, Milestone Global Solutions",
    },
    {
        "key": "nick_fisher", "name": "Nick Fisher",
        "aliases": ["Nicholas Fisher", "Nicholas T. Fisher"],
        "title": "VP Marketing", "company": "Zafran Security",
        "domain": "zafran.io", "account": "zafran",
        "linkedin": "https://www.linkedin.com/in/nicholastfisher",
        "location": "New York, United States",
        "persona": "economic_buyer",
        "exclusions": (
            "'Nick Fisher' is an extremely common name: the English cricketer, the Nick Fisher who "
            "writes about fishing/food for The Guardian, Nick Fisher the screenwriter, and multiple "
            "US sales professionals. Only the VP Marketing at Zafran Security "
            "(linkedin.com/in/nicholastfisher) is the subject."),
        "known_history": "",
    },
    {
        "key": "sanaz_yashar", "name": "Sanaz Yashar",
        "aliases": [],
        "title": "Co-Founder & CEO", "company": "Zafran Security",
        "domain": "zafran.io", "account": "zafran",
        "linkedin": "https://www.linkedin.com/in/sanaz-yashar",
        "location": "Tel Aviv, Israel / New York",
        "persona": "economic_buyer_exec",
        "exclusions": (
            "Any other Sanaz Yashar not associated with Zafran Security. Do not confuse Zafran "
            "Security with the saffron/spice brand 'Zafran' or the restaurant chains of that name."),
        "known_history": "Mandiant, Cybereason, Israeli Unit 8200 (verify before asserting)",
    },
    {
        "key": "alexander_semien", "name": "Alexander Semien",
        "aliases": ["Alex Semien"],
        "title": "Head of Growth", "company": "Cogent Security",
        "domain": "cogent.com", "account": "cogent",
        "linkedin": "https://www.linkedin.com/in/alexander-semien",
        "location": "United States",
        "persona": "champion",
        "exclusions": (
            "Cogent Security (cogent.com, the AI vulnerability-management startup founded 2024, "
            "$42M Series A led by Bain Capital Ventures) is NOT Cogent Communications (NASDAQ:CCOI, "
            "cogentco.com), Cogent Infotech, Cogent Analytics, Cogent Bank or Cogent Systems "
            "(biometrics). Discard anything about an ISP, a bank, a staffing firm or a biometrics vendor."),
        "known_history": "",
    },
    {
        "key": "cameron_coles", "name": "Cameron Coles",
        "aliases": [],
        "title": "VP of Marketing", "company": "Cogent Security",
        "domain": "cogent.com", "account": "cogent",
        "linkedin": "https://www.linkedin.com/in/cameroncoles",
        "location": "United States",
        "persona": "economic_buyer",
        "exclusions": (
            "Same Cogent disambiguation as above. Also exclude any Cameron Coles who is a musician "
            "or athlete rather than the B2B security marketing executive."),
        "known_history": "",
    },
    {
        "key": "vineet_edupuganti", "name": "Vineet Edupuganti",
        "aliases": [],
        "title": "Co-Founder & CEO", "company": "Cogent Security",
        "domain": "cogent.com", "account": "cogent",
        "linkedin": "https://www.linkedin.com/in/vineetedupuganti",
        "location": "San Francisco, California",
        "persona": "economic_buyer_exec",
        "exclusions": "Same Cogent disambiguation as above.",
        "known_history": "",
    },
    {
        "key": "ana_corio", "name": "Ana Corio",
        "aliases": ["Anastasia Corio"],
        "title": "Director of Demand Generation", "company": "Harmonic Security",
        "domain": "harmonic.security", "account": "harmonic",
        "linkedin": "https://www.linkedin.com/in/anastasiacorio",
        "location": "United States",
        "persona": "champion",
        "exclusions": (
            "Exclude the 'ana corio' profile in Allentown, Pennsylvania listing 'n/a' as employer "
            "(linkedin.com/in/ana-corio-1621a3145). Harmonic Security (harmonic.security, AI data "
            "security, founded 2023 by Alastair Paterson and Bryan Woolgar-O'Neil) is NOT Harmonic "
            "Inc. (NASDAQ:HLIT video delivery), NOT Harmonic the a16z mathematical-superintelligence "
            "company (harmonic.fun), NOT Harmonic Bionics or Harmonic Drive."),
        "known_history": "Material Security (Director of Demand Generation, Jul 2021 - Sep 2024)",
    },
    {
        "key": "tyler_chonoles", "name": "Tyler Chonoles",
        "aliases": [],
        "title": "Growth and Demand Gen Marketing Manager", "company": "Harmonic Security",
        "domain": "harmonic.security", "account": "harmonic",
        "linkedin": "https://www.linkedin.com/in/tyler-chonoles-106405a0",
        "location": "United States",
        "persona": "user",
        "exclusions": "Same Harmonic disambiguation as above.",
        "known_history": "",
    },
    {
        "key": "alastair_paterson", "name": "Alastair Paterson",
        "aliases": [],
        "title": "CEO & Co-Founder", "company": "Harmonic Security",
        "domain": "harmonic.security", "account": "harmonic",
        "linkedin": "https://www.linkedin.com/in/alastair-paterson-2586445",
        "location": "London, United Kingdom / San Francisco",
        "persona": "economic_buyer_exec",
        "exclusions": (
            "Same Harmonic disambiguation as above. He previously co-founded and led Digital Shadows "
            "(acquired by ReliaQuest 2022) — that history IS his. Exclude the Alastair Paterson who "
            "is a Scottish rugby player or an academic of the same name."),
        "known_history": "Digital Shadows co-founder & CEO (2011-2022, acquired by ReliaQuest)",
    },
    {
        "key": "mandar_marathe", "name": "Mandar Marathe",
        "aliases": [],
        "title": "VP Marketing", "company": "UPTIQ, Inc.",
        "domain": "uptiq.ai", "account": "uptiq",
        "linkedin": "https://www.linkedin.com/in/mandarmarathe",
        "location": "Pune, Maharashtra, India",
        "persona": "champion",
        "exclusions": (
            "'Mandar Marathe' is a common Maharashtrian name — exclude the Mandar Marathe who is a "
            "painter/artist, the one who is a mechanical engineer, and any who do not work at "
            "UPTIQ, Inc. (uptiq.ai, AI agents for banks/credit unions, CEO Snehal Fulzele)."),
        "known_history": "",
    },
]

BY_KEY = {p["key"]: p for p in PEOPLE}

if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    json.dump(PEOPLE, open(os.path.join(here, "roster.json"), "w"), indent=2)
    print(f"{len(PEOPLE)} people ->", os.path.join(here, "roster.json"))
    for p in PEOPLE:
        print(" ", p["key"].ljust(20), p["name"].ljust(22), p["title"][:34].ljust(36), p["linkedin"])
