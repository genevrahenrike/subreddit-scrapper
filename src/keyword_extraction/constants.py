"""
Constants used for keyword extraction.
"""

# Curated light stopword list: English + subreddit boilerplate
STOPWORDS = {
    # Articles, pronouns, prepositions, auxiliaries, etc.
    "a", "an", "the", "and", "or", "but", "if", "then", "else", "than",
    "for", "to", "from", "in", "on", "at", "of", "by", "with", "without",
    "into", "onto", "off", "over", "under", "about", "after", "before",
    "as", "is", "am", "are", "was", "were", "be", "been", "being",
    "this", "that", "these", "those", "it", "its", "they", "their", "them",
    "you", "your", "we", "our", "us", "he", "she", "his", "her", "hers",
    "i", "me", "my", "mine",
    "no", "not", "only", "also", "very", "more", "most", "less", "least",
    "so", "such", "can", "cannot", "cant", "could", "should", "would",
    "do", "does", "did", "doing", "done",
    "will", "wont", "won", "shall", "may", "might", "must",
    "all", "any", "some", "many", "much", "few", "several", "various",
    "own", "same", "other", "another", "each", "every", "either", "neither",
    "here", "there", "where", "when", "why", "how",
    "what", "which", "who", "whom", "whose",
    # Common subreddit boilerplate
    "welcome", "subreddit", "community", "official", "unofficial",
    "dedicated", "place", "space", "home", "discussion", "discuss", "talk",
    "share", "sharing", "post", "posts", "posting", "please", "read", "rules",
    "join", "fans", "fan", "related", "anything", "everything", "everyone",
    "anyone", "someone", "something", "stuff", "things",
    "news", "updates", "help",
    "about", "focused", "focusedon", "focus",
    "series", "tv", "show", "shows", "movie", "movies", "film", "films",
    "game", "games", "gaming", "videogame", "videogames",
    "forum", "sub", "reddit", "r",
    # Geography broad fillers
    "world", "global", "international",
    # Frequency and connector words
    "including", "include", "includes", "etc",
    # Numbers written in words (light)
    "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    # Cleanup for common artifacts and generic filler in bios
    "nother",  # from A(nother)
    "amp",     # from &
    "sn",      # local acronym seen in some descriptions
    "safe", "work", "works", "working", "great",
    # Media/generic content terms that often add noise
    "collection", "collections", "picture", "pictures", "video", "videos",
    "photo", "photos", "image", "images", "pic", "pics", "gallery",

    # Calendar months and common abbreviations (generic timeline chatter)
    "january", "february", "march", "april", "june", "july", "august",
    "september", "october", "november", "december",
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",

    # Generic colloquialisms often present in posts
    "guys",
}

# Common suffix/prefix clues to heuristically segment concatenated names (lowercase)
HEURISTIC_SUFFIXES = [
    "club", "food", "house", "houses", "baking", "cooking", "music", "girls",
    "boys", "games", "game", "garden", "gardening", "coding", "code", "design",
    "dev", "devs", "dogs", "dog", "cats", "cat", "jobs", "job", "news", "art",
    "arts", "sports", "sport", "cars", "car", "coin", "coins", "crypto",
    "market", "markets", "fashion", "makeup", "beauty", "support",
    "trading", "stocks", "nails", "drama", "school", "schools", "theory",
    "gardeners", "photography",
    "fc",  # football club
]

# Acronym and token expansions (lowercase key -> list of expansions)
EXPANSIONS = {
    "fc": ["football club"],
    "uk": ["united kingdom"],
    "us": ["united states"],
    "usa": ["united states"],
    "eu": ["europe"],
    "3ds": ["nintendo 3ds"],
    "ai": ["artificial intelligence"],
    "ml": ["machine learning"],
    "mlops": ["machine learning operations"],
    "ux": ["user experience"],
    "ui": ["user interface"],
    "diy": ["do it yourself"],
    "rpg": ["role playing game"],
    "ttrpg": ["tabletop role playing game"],
    "fps": ["first person shooter"],
}
# Tokens to trim from the tail of seed phrases during composition (kept deterministic and small)
COMPOSE_TRIM_TAIL_TOKENS = {
    "minute", "minutes", "hour", "hours", "day", "days",
    "today", "yesterday", "tomorrow", "question", "help"
}