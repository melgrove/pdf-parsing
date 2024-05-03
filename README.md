# PDF Parsing Challenge
## Problem
Given a PDF that has been scraped, it must be programatically converted it into the standardized key value format by extracting the necessary information. 
### Requirements
- **Deterministic**: has to have the same output given the same input every single time 
- **Know when it's wrong**: since the PDF input is out of its control, it needs to know when it has failed to extract
- **Account for within-target variation**: has to work for PDF variations within a target
- **Account for between-target variation**: has to work for PDF variations between different targets (hardest problem)
## Solution
### High level steps at runtime
1. **Parse the PDF into an extraction input format, usually just text**
	There is a dichotomy between using OCR and source text extraction, [this](https://pypdf.readthedocs.io/en/stable/user/extract-text.html) seems to outline some of the tradeoffs pretty well.

2. **Extract the standardized entities from the PDF based on deterministic rules, accounting for within-target variation**
	There are a couple different ways in which we do extraction. Here is what I can think of right now:
	- Typical statistical NLP *named-entity recognition* based on using a pre-trained model that detects surrounding text with a vector representation of semantic meaning. *example: extract all entities which are recognized with the pre-trained label "date"*
	- Text extraction by prompting a large language model (LLM). The complete non-starter with this is that the best LLMs are hosted by a company (OpenAI, Google, etc), and to use them, they need access to your data. In our case the data is sensitive target data which we have been trusted to keep secure, so it does not seem appropriate to use a hosted LLM. However, there are some fairly good open source LLMs that we could run locally (Llama 2 variants, Falcon 40B, etc) which would solve this problem. *example (LLM prompt): extract all text, and surrounding 100 characters from the pasted document below which are dates {parsed pdf text}*
	- Deterministic text pattern matching rule. *example (regex capture group):* `/redacted : (.*?)\n/`
	- Strict visual spacing based rule. *example: extract text which is one to two inches from the top and two to three inches from the bottom of the second page*
	- PDF styling based rules. *example: extract text that is font size 18px and color hex 0324fc*
	- More complicated computer vision models for visually distinguishing where something is based off of a raster image of the PDF 
	The first two methods are the most powerful and automated, but they function as a black box and are probabilistic, meaning that you will not get the same result every time. This limitation makes them unusable as a runtime tool (running them every time a PDF needs to be parsed), but they still can be used for precomputing deterministic runtime extraction rules. This is the idea that I'm proposing later in the doc.
	
3. **Transform the extracted portions into desired format**

4. **Run the runtime tests to make sure nothing unexpected has happened**
	 There should be a runtime test system that makes sure that the parsed result follows the pattern we expect. This specific PDF parsing problem is somewhat difficult because we have to make a system that can parse a result from a black box system (target PDF generation service) which potentially could completely change its output without notice. When this happens we want our parser to throw an error and not parse erroneously, so we know to update the system. Type II error (false negative failed test, erroneous parsing allowed through, client trust eroded) has a much higher negative effect than type I error (false positive failed test, valid result rejected, workflow fails maybe another one can be tried), so the test system should be strict.

	 In hindsight I think that this isn't necessarily needed as its own step because the extraction step likely enforces this in practice if strict enough matching rules are written.
### High level development steps
1. Programmer visually looks at the PDF to see where all of the entities are, and also parses it into the extraction input format for comparison
2. Programmer compares the two, and for each entity writes a extraction rule, making sure it works for all within-target PDF variation
3. Programmer writes the transformation code for each entity if needed
4. Programmer writes the runtime tests for each entity
The main point is that the programmer does this *for every target*, because between-target is so high that it can only reasonably be accounted for by having entirely separate code for each target. The problem with this is that it is very time consuming for the programmer, and many of the extraction rules, parsing, and runtime tests are going to be very similar across utilities. I think that the separation of code is unavoidable, however the generation of separate code can be generalized.

**An aside: speeding up development time with NLP precomputation**  
Here is what I think is an important insight: even though powerful probabilistic models can't be used at runtime, they can still be used during development as a form of precomputation to vastly speed up generation time of runtime code. The idea is that you use NLP models to help the developer generate extraction code, instead of running the models for every conversion. This could change the development steps to the following:
1. NLP model like an LLM inputs the parsed PDF and suggests to the programmer where each desired entity is in the document
2. If suggestion is correct, programmer indicates so and the NLP model target generates an extraction rule for it
3. Programmer still needs to personally verify that each entity has been handled correctly, but most of the work has been done for them
## Implementation
*Note: using MacOS, Python 3.8.2, and pip 20.0.2*
### Extraction
The main challenge is accounting for within-target variation in a way that maintains code quality. What I decided to do is make a class `EntityExtractor` which provides a nice interface for defining the rules for extraction. It provides two patterns to account for within-target variation:
	1. Use a single extractor instance and make the matching rules flexible enough
	2. Define multiple extractor instances which together cover all PDF variations, and set a test for when each should be used. When parsing the PDF, you can choose which extractor to use with `EntityExtractor.pick_instance`. Extractor functionality can be shared between instances by creating new instances from copying old ones, and then adding new rules.
The idea is that most of the extraction rules are the same across a single target, but some there are some differences, so you want to account for those differences by having different extractors without having to redefine the shared rules for each of them. The API is loosely documented with docstrings and type hints.

**Tables**
`EntityExtractor` uses a start and end pattern to get the substring that just contains the table. It then uses a separator pattern to determine where to split each column of each row. It then does some substitution to ensure reserved patterns don't get split on the separator (like when separator is " " and a known value is a date like "Aug 08, 22" which contains the separator). Finally, the extraction rules specify which column index to extract from.
### Formatting
I took a similar approach to extraction with the formatting instance `EntityFormatter`, which has the same `pick_instance` pattern.