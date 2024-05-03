import dateparser

regex = {
    # Unclear if single digit days will have a leading zero or not, so handle both
    "MMM DD, YYYY": r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{1,2}, \d{4}\b',
    "MMM DD, YY": r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{1,2}, \d{2}\b'
}

class Parse:
    def strip_number(value):
        # Remove decimal point, comma, and leading $
        return int(str(value).replace(".", "").replace(",", "").replace("$", ""))

    def date(value: str):
        parsed_date = dateparser.parse(value)
        return parsed_date.strftime("%Y-%m-%d")