from pypdf import PdfReader
from typing import Union, Pattern, Callable
import re
from data_model import redacted, redacted2

class PDFParser:
    """Convert a PDF file into a single string."""

    def source_text_extraction(file):
        reader = PdfReader(file)
        pdf_text = ""
        for page in reader.pages:
            pdf_text += f"{page.extract_text()}\n"
        return pdf_text

    # had trouble installing tesseract so leaving this as a stub
    def ocr(file):
        pass

class EntityExtractor:
    """Interface for defining and executing entity extraction rules.

    Provides methods for the following functionality:
        1. Defining extraction rules
        2. Extracting entities from a PDF based on the set rules
        3. Choosing which extraction instance to use based on the PDF

    Allows for two patterns to account for within-target variation:
	    1. Use a single extractor instance and make the matching rules
           flexible enough
	    2. Define multiple extractor instances which together cover all
           PDF variations,and set a test for when each should be used. When
           parsing the PDF, you can choose which extractor to use with 
           `EntityExtractor.pick_instance`. Extractor functionality can be 
           shared between instances by creating new instances from copying
           old ones, and then adding new rules.
    """

    def __init__(self):
        self.extracted = redacted.copy()
        self._matchers: dict[str, Union[None, Matcher]] = redacted.copy()
        self._redacted_matchers = redacted2.copy()

        self._redacted_delim = " "
        self._redacted_subset_pattern = None
        self._redacted_start = None
        self._redacted_end = None
        self._redacted_filters = []
        self._redacted_reserved_patterns = []

        self._validity_check_pattern = None
        self._must_exist = []
        self._redacted_must_exist = []

    def set(self, 
            entity_name: str, 
            matcher: Union[str, Callable, float, int], 
            static: bool = False, 
            redacted: bool = False,
            outside_table: bool = False):
        """Set entity matching rules.
        
        Accepts either a string which is interpreted as
        regex, a callback function which is directly called every extraction, or a primitive for
        static matchers (entity is set to the same value every time). The matcher class is chosen
        implicitly based off of passed type
        """

        matcher_dict = self._redacted_matchers if redacted is True else self._matchers
        
        if entity_name not in matcher_dict:
            raise Exception(f"Set entity {entity_name} does not exist in the data model")
        
        must_exist = entity_name in (self._redacted_must_exist if redacted else self._must_exist)
        if type(matcher) in [str, float, int]:
            # static primative
            if static is True:
                matcher_instance = StaticMatcher(matcher, entity_name, must_exist)
            elif redacted is True:
                if outside_table is True:
                    matcher_instance = RegexMatcher(matcher, entity_name, must_exist)
                else:
                    matcher_instance = TableMatcher(matcher, entity_name, must_exist)
            # regex
            else:
                matcher_instance = RegexMatcher(matcher, entity_name, must_exist)
        # custom callback
        else:
            matcher_instance = CallbackMatcher(matcher, entity_name, must_exist)
        # save the instance
        matcher_dict[entity_name] = matcher_instance

    def set_must_exist(self, entities = [], all_entities = False, redacted = False):
        """Set assertion for which entities must have a value parsed at runtime."""

        must_exist = self._redacted_must_exist if redacted else self._must_exist
        if all_entities:
            must_exist.extend(list(redacted.keys() if redacted else redacted2.keys()))
        else:
            must_exist.extend(entities)

    def set_redacted_delim(self, delim: str):
        """Set the pattern to split redacted table columns on."""

        self._redacted_delim = delim

    def set_redacted_boundary(self, start: str, start_inclusive: bool, end: str, end_inclusive: bool):
        """Set the pattern to get the redacted table substring."""

        # Note: this will break if the start or end patterns include unescaped parenthesis
        start_pattern = "(" + start if start_inclusive else start + "("
        end_pattern = end + ")" if end_inclusive else ")" + end
        self._redacted_subset_pattern = re.compile(rf"{start_pattern}.+?{end_pattern}", flags = re.MULTILINE | re.DOTALL)

    def set_redacted_reserved_cell_patterns(self, patterns: list):
        """Set the patterns which are excluded from redacted table column splitting."""

        self._redacted_reserved_patterns = patterns

    def set_redacted_filter(self, column_index: int, matcher: str):
        """Set a pattern to filter the parsed redacted table on."""

        self._redacted_filters.append({
            "column_index": column_index,
            "matcher": re.compile(matcher, re.MULTILINE),
        })

    def split_table_rows(self, row_text: str) -> list:
        if len(self._redacted_reserved_patterns) > 0:
            placeheld = []
            # helper to save the reserved patterns
            def hold_place_of_match(match):
                placeheld.append(match.group())
                placeheld_index = len(placeheld) - 1
                return f"__placeholder{placeheld_index}__"
            # substitute the temporary placeholder for all of the reserved matches
            substituted_row = re.sub(
                r"|".join(self._redacted_reserved_patterns),
                hold_place_of_match,
                row_text
            )
            # now split on the delimiter since reserved patterns have been protected
            substituted_row = re.split(self._redacted_delim, substituted_row)
            # resubstitute back in the reserved patterns
            row_with_reserved = [re.sub(
                r"__placeholder(\d+)__",
                lambda match: placeheld[int(match.group(1))],
                cell
            ) for cell in substituted_row]
            return row_with_reserved
        else:
            return re.split(self._redacted_delim, row_text)
    
    def filter_row(self, row: list) -> bool:
        for filter in self._redacted_filters:
            if filter["matcher"].search(row[filter["column_index"]]):
                continue
            else:
                return False
        return True

    def extract(self, pdf_text: str) -> dict:
        """Extract entities from the PDF with the set rules."""

        extracted = redacted.copy()
        # Extract every entity with its saved matcher
        for entity_name, matcher in self._matchers.items():
            extracted[entity_name] = matcher.match(pdf_text) if matcher is not None else None
        
        # redacted table recognition
        extracted["redacteds"] = []
        redacted_table_match = self._redacted_subset_pattern.search(pdf_text)
        if redacted_table_match:
            redacted_table = redacted_table_match.group(1)
            table_rows = redacted_table.split("\n")
            table_rows_with_reserved = [self.split_table_rows(row) for row in table_rows]
            # Make sure rows have the same number of cells
            n_columns = len(table_rows_with_reserved[0])
            if not all([len(row) == n_columns for row in table_rows_with_reserved]):
                raise Exception("Number of redacted row columns differs across rows")

            # Filter redacted rows based on filtering rules
            table_rows_with_reserved = filter(self.filter_row, table_rows_with_reserved)

            # Insert each redacted row
            for row in table_rows_with_reserved:
                redacted = {}
                for redacted_entity_name, matcher in self._redacted_matchers.items():
                    redacted[redacted_entity_name] = matcher.match(pdf_text, row) if matcher is not None else None
                extracted["redacteds"].append(redacted)

        return extracted          

    def set_validity_check(self, matcher: Union[str, Callable]):
        """Set the pattern which decides if the instance will be used."""

        self._validity_check_pattern = re.compile(matcher, re.MULTILINE)

    def check_valid(self, pdf_text: str) -> bool:
        return self._validity_check_pattern is not None and self._validity_check_pattern.search(pdf_text)

    @classmethod
    def pick_instance(cls, pdf_text, default, instances: list):
        """Return the valid instance for the PDF."""

        # Instances passed as earliest param gets priority if multiple matches
        for extractor in instances:
            if not isinstance(extractor, cls):
                raise Exception("Extractor passed is not an instance of EntityExtractor")
            if extractor.check_valid(pdf_text):
                return extractor
        return default


class Matcher:
    """Finds an entity from text based on a specific matching strategy."""

    def __init__(self, matcher, entity_name, must_exist):
        self.matcher = matcher
        self.entity_name = entity_name
        self.must_exist = must_exist
    
    def validate(self, match):
        if match is None and self.must_exist is True:
            raise Exception(f"Entity {self.entity_name} has not been extracted and is not allowed to be None")
        else:
            return match

class RegexMatcher(Matcher):
    def __init__(self, matcher, entity_name, must_exist):
        matcher = re.compile(matcher, re.MULTILINE)
        super(RegexMatcher, self).__init__(matcher, entity_name, must_exist)
    
    def match(self, *args):
        entity_match = self.matcher.search(args[0])
        if entity_match:
            return self.validate(entity_match.group(1))
        else:
            return self.validate(None)

# For this class the matcher is the index of the column in the redacted table
class TableMatcher(Matcher):
    def match(self, *args):
        row_data = args[1]
        column_index = self.matcher
        if len(row_data) > column_index:
            return self.validate(row_data[column_index])
        else:
            return self.validate(None)     

class StaticMatcher(Matcher):
    def match(self, *args):
        return self.validate(self.matcher)

class CallbackMatcher(Matcher):
    def match(self, *args):
        return self.validate(self.matcher(args[0]))

class EntityFormatter:
    """Interface for defining and executing entity formatting rules."""

    def __init__(self):
        self._entity_formatter_lookup = {}
        self._redacted_entity_formatter_lookup = {}
        self._format_entities_when_none = []
        self._redacted_format_entities_when_none = []
        self._validity_check_pattern = None

    def set(self, entities: list, formatters: list, redacted = False, format_none = False):
        lookup = self._redacted_entity_formatter_lookup if redacted else self._entity_formatter_lookup
        if format_none:
            format_list = self._redacted_format_entities_when_none if redacted else self._format_entities_when_none
            format_list.extend(entities)
        for entity_name in entities:
            lookup[entity_name] = formatters

    def format(self, extracted: dict):
        formatted_extracted = extracted.copy()
        for entity_name, entity_value in extracted.items():
            if entity_name == "redacteds":
                for redacted_index in range(len(extracted["redacteds"])):
                    redacted = extracted["redacteds"][redacted_index]
                    for redacted_entity_name, redacted_entity_value in redacted.items():
                        # if None value check whitelist to see if formatting should still happen
                        if redacted_entity_value is None and redacted_entity_name not in self._redacted_format_entities_when_none:
                            continue
                        if redacted_entity_name in self._redacted_entity_formatter_lookup:
                            for formatter in self._redacted_entity_formatter_lookup[redacted_entity_name]:
                                redacted_entity_value = formatter(redacted_entity_value)
                            formatted_extracted["redacteds"][redacted_index][redacted_entity_name] = redacted_entity_value
            elif entity_name in self._entity_formatter_lookup:
                # if None value check whitelist to see if formatting should still happen
                if entity_value is None and entity_name not in self._format_entities_when_none:
                    continue
                # run every formatting function in order and resave
                for formatter in self._entity_formatter_lookup[entity_name]:
                    entity_value = formatter(entity_value)
                formatted_extracted[entity_name] = entity_value
        return formatted_extracted
    
    def set_validity_check(self, matcher: Union[str, Callable]):
        self._validity_check_pattern = re.compile(matcher, re.MULTILINE)

    def check_valid(self, pdf_text) -> bool:
        return self._validity_check_pattern is not None and self._validity_check_pattern.search(pdf_text)

    # Instances passed as earliest param gets priority if multiple matches
    @classmethod
    def pick_instance(cls, pdf_text, default, instances: list):
        for formatter in instances:
            if not isinstance(formatter, cls):
                raise Exception("Formatter passed is not an instance of EntityFormatter")
            if formatter.check_valid(pdf_text):
                return formatter
        return default