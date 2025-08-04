"""
Enhanced Question Extraction Module
Provides sophisticated question detection from scraped polling content with LLM fallback
"""

import re
import string
from typing import List, Dict, Tuple, Optional
import asyncio

class QuestionExtractor:
    """Enhanced question extraction with multiple detection methods and LLM fallback"""
    
    def __init__(self, llm_instance=None):
        self.llm = llm_instance  # LLM instance for fallback extraction
        
        # Question patterns for different types of survey questions
        self.question_patterns = [
            # Direct questions with question marks
            r'[A-Z][^.!?]*\?',
            # Questions starting with common question words
            r'\b(Do you|Would you|Are you|Have you|Did you|Will you|Should|Can|Could|Would|Is|Are|Does|Do|Have|Has|Had|Will|Would|Should|Can|Could|Might|May)\b[^.!?]*[.!?]',
            # Questions about approval/opinion
            r'\b(approve|disapprove|favorable|unfavorable|support|oppose|trust|distrust|satisfied|dissatisfied)\b[^.!?]*[.!?]',
            # Questions about voting intention
            r'\b(vote for|vote|election|candidate|president|senator|governor|representative)\b[^.!?]*[.!?]',
            # Questions about policy issues
            r'\b(immigration|economy|healthcare|education|environment|taxes|budget|deficit|jobs|unemployment|inflation)\b[^.!?]*[.!?]',
            # Questions about demographics
            r'\b(age|gender|race|ethnicity|income|education|region|party|ideology|religion)\b[^.!?]*[.!?]',
            # Questions about current events
            r'\b(COVID|pandemic|vaccine|mask|lockdown|stimulus|relief|recovery|recession)\b[^.!?]*[.!?]',
            # Questions about political figures
            r'\b(Biden|Trump|Harris|Pence|Obama|Bush|Clinton|Sanders|Warren|Pelosi|McConnell)\b[^.!?]*[.!?]',
        ]
        
        # Question word patterns
        self.question_words = [
            'what', 'how', 'why', 'when', 'where', 'which', 'who', 'whom', 'whose',
            'do', 'does', 'did', 'have', 'has', 'had', 'will', 'would', 'should',
            'can', 'could', 'may', 'might', 'must', 'shall', 'is', 'are', 'was', 'were'
        ]
        
        # Survey-specific patterns
        self.survey_patterns = [
            r'(\d+\.\s*[^.!?]*[.!?])',  # Numbered questions
            r'([A-Z][^.!?]*\?)',  # Questions starting with capital letters
            r'(\b[^.!?]*\b(approve|disapprove|support|oppose|favorable|unfavorable)\b[^.!?]*[.!?])',
            r'(\b[^.!?]*\b(vote|election|candidate|president)\b[^.!?]*[.!?])',
        ]
        
        # Cleanup patterns
        self.cleanup_patterns = [
            (r'^\d+[\.\)]\s*', ''),  # Remove numbering
            (r'^[-•*]\s*', ''),  # Remove bullets
            (r'^\s+', ''),  # Remove leading whitespace
            (r'\s+$', ''),  # Remove trailing whitespace
            (r'\s+', ' '),  # Normalize whitespace
        ]
    
    async def extract_questions_from_content(self, content: str, url: str = "", max_questions: int = 15, min_questions: int = 3) -> List[str]:
        """
        Extract questions from scraped content using multiple detection methods with LLM fallback
        
        Args:
            content: The scraped content text
            url: Source URL for context
            max_questions: Maximum number of questions to return
            min_questions: Minimum questions needed before using LLM fallback
            
        Returns:
            List of extracted questions
        """
        if not content:
            return []
        
        print(f"🔍 Starting question extraction from content ({len(content)} chars)")
        
        # STEP 1: Try pattern-based extraction first
        questions = []
        
        # Method 1: Direct question mark detection
        pattern_questions = self._extract_question_mark_questions(content)
        questions.extend(pattern_questions)
        print(f"   Found {len(pattern_questions)} questions with question marks")
        
        # Method 2: Pattern-based detection
        regex_questions = self._extract_pattern_questions(content)
        questions.extend(regex_questions)
        print(f"   Found {len(regex_questions)} questions with regex patterns")
        
        # Method 3: Survey-specific detection
        survey_questions = self._extract_survey_questions(content)
        questions.extend(survey_questions)
        print(f"   Found {len(survey_questions)} survey-specific questions")
        
        # Method 4: Sentence-based detection
        sentence_questions = self._extract_sentence_questions(content)
        questions.extend(sentence_questions)
        print(f"   Found {len(sentence_questions)} sentence-based questions")
        
        # Clean and deduplicate questions
        cleaned_questions = self._clean_and_deduplicate_questions(questions)
        print(f"   After cleaning: {len(cleaned_questions)} unique questions")
        
        # STEP 2: Check if we need LLM fallback
        if len(cleaned_questions) < min_questions and self.llm:
            print(f"⚡ Only found {len(cleaned_questions)} questions, using LLM fallback...")
            try:
                llm_questions = await self._extract_questions_with_llm(content, url, max_questions)
                print(f"   LLM found {len(llm_questions)} additional questions")
                
                # Combine pattern-based and LLM questions
                all_questions = cleaned_questions + llm_questions
                final_questions = self._clean_and_deduplicate_questions(all_questions)
                print(f"   Combined total: {len(final_questions)} questions")
                
                return final_questions[:max_questions]
                
            except Exception as e:
                print(f"❌ LLM fallback failed: {e}")
                return cleaned_questions[:max_questions]
        
        print(f"✅ Pattern extraction sufficient: {len(cleaned_questions)} questions found")
        return cleaned_questions[:max_questions]
    
    async def _extract_questions_with_llm(self, content: str, url: str = "", max_questions: int = 15) -> List[str]:
        """
        Extract questions using LLM when pattern matching fails
        
        Args:
            content: The scraped content text
            url: Source URL for context
            max_questions: Maximum questions to extract
            
        Returns:
            List of questions extracted by LLM
        """
        if not self.llm:
            return []
        
        # Limit content length for LLM processing
        content_sample = content[:4000]  # Use first 4000 characters
        
        prompt = f"""
Extract EXISTING survey questions from this polling/survey content. Find questions that already exist - do NOT create new ones.

SOURCE: {url if url else "Polling Website"}

CONTENT:
{content_sample}

EXTRACTION RULES:
1. Only extract questions that already exist in the content
2. Questions must end with "?" or be clear survey questions
3. Questions should be 15-250 characters long
4. Focus on polling/survey questions (opinions, approval, voting, policy, demographics)
5. Return maximum {max_questions} questions
6. Format: One question per line, no numbering
7. If no actual questions found, return "NO_QUESTIONS_FOUND"

EXISTING SURVEY QUESTIONS:
"""
        
        try:
            response = await self.llm.ask(prompt, temperature=0.2)  # Low temperature for accuracy
            
            # Clean response and remove any Chinese characters if present  
            cleaned_response = self._remove_chinese_and_punct(str(response))
            
            if "NO_QUESTIONS_FOUND" in cleaned_response.upper():
                print("   LLM reported no questions found")
                return []
            
            # Parse questions from LLM response
            lines = cleaned_response.split('\n')
            llm_questions = []
            
            for line in lines:
                line = line.strip()
                if not line or len(line) < 15:
                    continue
                
                # Clean up formatting that LLM might add
                line = re.sub(r'^\d+[\.\)]\s*', '', line)  # Remove numbering
                line = re.sub(r'^[-•*]\s*', '', line)      # Remove bullets
                line = line.strip()
                
                # Validate as proper question
                if self._is_valid_question(line):
                    # Ensure it ends with ? if it's clearly a question
                    if not line.endswith('?') and self._should_have_question_mark(line):
                        line += '?'
                    
                    llm_questions.append(line)
                    
                    if len(llm_questions) >= max_questions:
                        break
            
            return llm_questions
            
        except Exception as e:
            print(f"Error in LLM question extraction: {e}")
            return []
    
    def _should_have_question_mark(self, text: str) -> bool:
        """Check if text should end with a question mark"""
        text_lower = text.lower()
        
        # Check for question starters
        question_starters = [
            'do you', 'would you', 'are you', 'have you', 'did you', 'will you',
            'should you', 'can you', 'could you', 'what', 'how', 'why', 'when',
            'where', 'which', 'who', 'whom', 'whose'
        ]
        
        for starter in question_starters:
            if text_lower.startswith(starter):
                return True
        
        # Check for question patterns in middle
        if any(word in text_lower for word in ['approve', 'support', 'favor', 'vote for']):
            return True
        
        return False
    
    def _remove_chinese_and_punct(self, text: str) -> str:
        """Remove Chinese characters and clean up text"""
        # Remove Chinese characters
        text = re.sub(r'[\u4e00-\u9fff]+', '', text)
        return text.strip()
    
    # [All the existing methods remain the same - _extract_question_mark_questions, 
    # _extract_pattern_questions, etc. - keeping them unchanged]
    
    def _extract_question_mark_questions(self, content: str) -> List[str]:
        """Extract questions that end with question marks"""
        questions = []
        lines = content.split('\n')
        
        for line in lines:
            line = line.strip()
            if line.endswith('?') and 15 <= len(line) <= 300:
                clean_line = self._clean_question_text(line)
                if clean_line and self._is_valid_question(clean_line):
                    questions.append(clean_line)
        
        return questions
    
    def _extract_pattern_questions(self, content: str) -> List[str]:
        """Extract questions using regex patterns"""
        questions = []
        
        for pattern in self.question_patterns:
            try:
                matches = re.finditer(pattern, content, re.IGNORECASE | re.MULTILINE)
                for match in matches:
                    question_text = match.group(0).strip()
                    clean_text = self._clean_question_text(question_text)
                    if clean_text and self._is_valid_question(clean_text):
                        questions.append(clean_text)
            except re.error:
                continue  # Skip invalid regex patterns
        
        return questions
    
    def _extract_survey_questions(self, content: str) -> List[str]:
        """Extract survey-specific questions"""
        questions = []
        
        for pattern in self.survey_patterns:
            try:
                matches = re.finditer(pattern, content, re.IGNORECASE | re.MULTILINE)
                for match in matches:
                    question_text = match.group(1).strip()
                    clean_text = self._clean_question_text(question_text)
                    if clean_text and self._is_valid_question(clean_text):
                        questions.append(clean_text)
            except (re.error, IndexError):
                continue
        
        return questions
    
    def _extract_sentence_questions(self, content: str) -> List[str]:
        """Extract questions from sentences that might be questions"""
        questions = []
        
        # Split into sentences
        sentences = re.split(r'[.!?]+', content)
        
        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) < 20 or len(sentence) > 300:
                continue
            
            # Check if sentence contains question indicators
            if self._contains_question_indicators(sentence):
                clean_text = self._clean_question_text(sentence)
                if clean_text and self._is_valid_question(clean_text):
                    questions.append(clean_text)
        
        return questions
    
    def _contains_question_indicators(self, text: str) -> bool:
        """Check if text contains indicators of being a question"""
        text_lower = text.lower()
        
        # Check for question words
        for word in self.question_words:
            if word in text_lower:
                return True
        
        # Check for survey-specific indicators
        survey_indicators = [
            'approve', 'disapprove', 'favorable', 'unfavorable',
            'support', 'oppose', 'trust', 'distrust',
            'satisfied', 'dissatisfied', 'vote', 'election',
            'candidate', 'president', 'senator', 'governor'
        ]
        
        for indicator in survey_indicators:
            if indicator in text_lower:
                return True
        
        return False
    
    def _clean_question_text(self, text: str) -> str:
        """Clean and normalize question text"""
        if not text:
            return ""
        
        # Apply cleanup patterns
        for pattern, replacement in self.cleanup_patterns:
            text = re.sub(pattern, replacement, text)
        
        # Remove excessive punctuation
        text = re.sub(r'[.!?]+$', '', text)  # Remove trailing punctuation
        text = re.sub(r'[.!?]{2,}', '.', text)  # Normalize multiple punctuation
        
        # Remove common survey artifacts
        text = re.sub(r'\([^)]*\)', '', text)  # Remove parenthetical content
        text = re.sub(r'\[[^\]]*\]', '', text)  # Remove bracketed content
        
        return text.strip()
    
    def _is_valid_question(self, text: str) -> bool:
        """Validate if text is a legitimate question"""
        if not text or len(text) < 15 or len(text) > 300:
            return False
        
        # Check for common invalid patterns
        invalid_patterns = [
            r'^\s*$',  # Empty or whitespace only
            r'^\d+$',  # Just numbers
            r'^[A-Z\s]+$',  # Just uppercase letters and spaces
            r'^[^\w\s]+$',  # Just punctuation
            r'copyright|all rights reserved|privacy policy',  # Legal text
            r'click here|read more|learn more',  # Navigation text
        ]
        
        for pattern in invalid_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return False
        
        # Must contain at least one letter
        if not re.search(r'[a-zA-Z]', text):
            return False
        
        return True
    
    def _clean_and_deduplicate_questions(self, questions: List[str]) -> List[str]:
        """Clean and remove duplicate questions"""
        cleaned = []
        seen = set()
        
        for question in questions:
            # Normalize for comparison
            normalized = re.sub(r'\s+', ' ', question.lower().strip())
            
            if normalized and normalized not in seen:
                seen.add(normalized)
                cleaned.append(question)
        
        return cleaned
    
    async def extract_questions_with_metadata(self, content: str, url: str = "", title: str = "") -> List[Dict]:
        """
        Extract questions with metadata for better context
        
        Args:
            content: The scraped content text
            url: The source URL
            title: The page title
            
        Returns:
            List of question dictionaries with metadata
        """
        questions = await self.extract_questions_from_content(content, url)
        
        question_objects = []
        for i, question in enumerate(questions):
            question_obj = {
                'question': question,
                'source': url,
                'title': title,
                'extraction_method': 'enhanced_extraction_with_llm',
                'confidence': self._calculate_confidence(question),
                'question_number': i + 1
            }
            question_objects.append(question_obj)
        
        return question_objects
    
    def _calculate_confidence(self, question: str) -> float:
        """Calculate confidence score for question extraction"""
        confidence = 0.5  # Base confidence
        
        # Boost confidence for questions with question marks
        if question.endswith('?'):
            confidence += 0.3
        
        # Boost confidence for questions with question words
        question_lower = question.lower()
        for word in self.question_words:
            if word in question_lower:
                confidence += 0.1
                break
        
        # Boost confidence for survey-specific terms
        survey_terms = ['approve', 'disapprove', 'support', 'oppose', 'vote', 'election']
        for term in survey_terms:
            if term in question_lower:
                confidence += 0.1
                break
        
        # Penalize very short or very long questions
        if len(question) < 20:
            confidence -= 0.2
        elif len(question) > 200:
            confidence -= 0.1
        
        return min(confidence, 1.0)  # Cap at 1.0

# Backwards compatibility functions
async def extract_questions_from_content_async(content: str, llm_instance=None, url: str = "", max_questions: int = 15) -> List[str]:
    """
    Async function for extracting questions with LLM fallback
    """
    extractor = QuestionExtractor(llm_instance)
    return await extractor.extract_questions_from_content(content, url, max_questions)

def extract_questions_from_content(content: str, max_questions: int = 15) -> List[str]:
    """
    Synchronous function for backward compatibility (pattern-based only)
    """
    extractor = QuestionExtractor()
    # Use asyncio.run for sync compatibility, but only pattern-based extraction
    questions = []
    
    # Pattern-based extraction only (no LLM)
    questions.extend(extractor._extract_question_mark_questions(content))
    questions.extend(extractor._extract_pattern_questions(content))
    questions.extend(extractor._extract_survey_questions(content))
    questions.extend(extractor._extract_sentence_questions(content))
    
    # Clean and deduplicate
    cleaned_questions = extractor._clean_and_deduplicate_questions(questions)
    return cleaned_questions[:max_questions]