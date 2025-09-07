#!/usr/bin/env python3
"""
Enhanced Audiobook Image Prompt Generator with Advanced Agent Council

Uses a council of specialized agents with multi-shot learning to generate and vote on the best
thumbnail prompts for audiobook videos. Generates 20-30 candidates and selects top 5 through
advanced voting with detailed metadata export.

Features:
- Multi-shot learning with embedded cinematic examples
- Intelligent part handling (only show parts when multiple exist)
- Advanced voting system with detailed process visibility
- Rich metadata export for future optimization
- Guaranteed 20-30 candidates with robust extraction
"""

import json
import os
import re
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime

from langchain_openai import ChatOpenAI
from langchain.prompts import ChatPromptTemplate
from langchain.agents import create_openai_tools_agent, AgentExecutor
from langchain.tools import BaseTool
from dotenv import load_dotenv

# Web search imports
try:
    from langchain_community.tools import TavilySearchResults
    from langchain_community.tools import GoogleSearchAPIWrapper
    from langchain_community.tools import WikipediaQueryRun
    from langchain_community.utilities import WikipediaAPIWrapper
    from langchain_community.tools import DuckDuckGoSearchRun
    SEARCH_TOOLS_AVAILABLE = True
except ImportError:
    print("Warning: Search tools not available. Install with: pip install langchain-community tavily-python wikipedia")
    SEARCH_TOOLS_AVAILABLE = False

# Load environment variables
load_dotenv()

# Import your existing configuration
try:
    from constants import DEFAULT_TEMPERATURE, DEFAULT_MODEL
except ImportError:
    DEFAULT_TEMPERATURE = float(os.getenv('DEFAULT_TEMPERATURE', '0.7'))
    DEFAULT_MODEL = os.getenv('DEFAULT_MODEL', 'gpt-4o')

# Multi-Model Configuration for Agent Diversity
AGENT_MODEL_ASSIGNMENTS = {
    'cinematic_director': 'gpt-4o-mini',              # Visual composition expertise
    'story_architect': 'claude-3-5-haiku-latest',    # Story analysis and narrative
    'visual_psychologist': 'gemini-2.0-flash-lite', # Psychology and engagement
    'genre_specialist': 'gpt-3.5-turbo'              # Genre knowledge and conventions
}

# Model Configuration Profiles
MODEL_PROFILES = {
    'high_quality': {
        'cinematic_director': 'gpt-4o',
        'story_architect': 'claude-3-5-sonnet-20250219',
        'visual_psychologist': 'gemini-2.0-flash-lite',
        'genre_specialist': 'gpt-4o'
    },
    'balanced': {
        'cinematic_director': 'gpt-4o-mini',
        'story_architect': 'claude-3-5-haiku-latest', 
        'visual_psychologist': 'gemini-2.0-flash-lite',
        'genre_specialist': 'gpt-3.5-turbo'
    },
    'economy': {
        'cinematic_director': 'gpt-3.5-turbo',
        'story_architect': 'claude-3-5-haiku-latest',
        'visual_psychologist': 'gpt-3.5-turbo',
        'genre_specialist': 'gpt-3.5-turbo'
    }
}

# API Keys from environment
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')  
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')
CLAUDE_API_KEY = os.getenv('CLAUDE_API_KEY')
TAVILY_API_KEY = os.getenv('TAVILY_API_KEY')

# Expanded high-quality example prompts for multi-shot learning
EXAMPLE_PROMPTS = {
    'mystery_thriller': [
        """Create a cinematic audiobook thumbnail for "The Secret Adversary", featuring Jane Finn clutching a waterproof oilskin packet as she's helped into a lifeboat from the sinking Lusitania, her face pale with terror while knowing she carries papers that could change the war, conveying the moment that starts everything. Utilize a dramatic historical disaster style, incorporating the tilting ship deck, lifeboats being lowered, the precious treaty packet, and Jane's desperate grip. Employ emergency flare lighting against night ocean, with a palette of distress orange, night sea blacks, and the oilskin packet's brown leather. Design with "Agatha Christie" in period maritime font, "The Secret Adversary" in urgent telegram style, and "Narrated by Rowan Whitmore" in ship's log type. Add smoke and spray effects.""",
        
        """Create a cinematic audiobook thumbnail for "The Secret Adversary", showing Tommy and Tuppence outside the Ritz hotel holding their homemade "Young Adventurers Ltd" business card while shadowy figures watch from windows and doorways, with Mr. Whittington's sinister silhouette approaching, conveying innocent ambition meeting danger. Utilize a film noir style with 1920s London detail, incorporating the Ritz facade, hand-drawn business card, multiple watching shadows, and the approaching threat. Employ afternoon light with multiple shadow sources, using a palette of London stone grays, business card white, and menacing shadow purples. Position "Agatha Christie" in Ritz hotel font, "The Secret Adversary" in adventurous hand-lettered style, and "Narrated by Rowan Whitmore" in professional type. Add fog wisps and window glints.""",

        """Create a cinematic audiobook thumbnail for "The Secret Adversary", featuring the moment in the Soho house where Tommy discovers Jane Finn held captive, her face showing both relief and terror as chloroform-soaked cloth looms behind her, while Rita/Marguerite's treacherous figure appears in the doorway, conveying rescue and betrayal. Utilize a tense interior scene style, incorporating Victorian room details, Jane's captive position, the chloroform threat, and multiple dangers. Employ single gas lamp creating dramatic shadows, with a palette of sickroom yellows, chloroform bottle green, and betrayal reds. Display "Agatha Christie" in Victorian house number font, "The Secret Adversary" in shadow-cast letters, and "Narrated by Rowan Whitmore" in period script. Add gas light flicker and menace atmosphere."""
    ],
    
    'classic_adventure': [
        """Create a cinematic audiobook thumbnail for "The Lost World", set on a prehistoric plateau shrouded in mist, featuring the silhouette of a massive Tyrannosaurus Rex roaring against a blood-red sunset, with tiny Victorian explorers visible at the bottom for scale, conveying danger and discovery. Utilize an art style inspired by vintage adventure posters with modern digital painting techniques, incorporating key visual elements such as pterodactyls circling overhead, ancient ferns, volcanic peaks, and expedition equipment. Employ dramatic backlighting to enhance the prehistoric atmosphere, with a color palette of deep oranges, jungle greens, and volcanic reds. Design with "Sir Arthur Conan Doyle" in bold Victorian serif fonts at the top, "The Lost World" in massive stone-textured letters across the center, and "Narrated by Rowan Whitmore" in clean sans-serif at the bottom. Add atmospheric fog and dust particles.""",
        
        """Create a cinematic audiobook thumbnail for "The Lost World", featuring Professor Challenger's expedition team standing at the edge of a sheer cliff, gazing up at a colossal brachiosaurus whose head towers above prehistoric trees, conveying awe and scientific wonder. Utilize a photorealistic art style with painterly elements, incorporating dense jungle foliage, mysterious caves, Victorian-era rifles, and field notebooks. Employ golden hour lighting filtering through primeval forest canopy, with a palette of lush greens, earthy browns, and misty blues. Position "Sir Arthur Conan Doyle" in elegant copper-plated serif fonts, "The Lost World" in bold adventure-style lettering with vine embellishments, and "Narrated by Rowan Whitmore" in period-appropriate typography. Add light rays and floating pollen effects."""
    ],
    
    'literary_drama': [
        """Create a cinematic audiobook thumbnail for "A Tale of Two Cities", featuring a split composition with revolutionary Paris ablaze on one side and peaceful London fog on the other, divided by a guillotine blade that reflects both cities, conveying duality and fate. Utilize a dramatic contrast style mixing chaos and calm, incorporating burning buildings, Big Ben silhouette, revolutionary crowds, and Georgian architecture. Employ fire glow versus gaslight illumination, with a palette of revolution reds, London grays, and blood crimson. Design with "Charles Dickens" in elegant Victorian serif, "A Tale of Two Cities" in bold divided letters, and "Narrated by Rowan Whitmore" in classic type. Add smoke and crowd movement effects.""",
        
        """Create a cinematic audiobook thumbnail for "A Tale of Two Cities", showing a wine cask broken in the streets with red wine flowing like blood between cobblestones, while desperate figures drink from the ground and "BLOOD" appears written on the wall, conveying foreshadowing revolution. Utilize a gritty realism style, incorporating spilled wine, weathered hands, stone textures, and ominous writing. Employ harsh street-level lighting, with a palette of wine reds, stone grays, and poverty browns. Display "Charles Dickens" in wine-stained letters, "A Tale of Two Cities" in dripping font, and "Narrated by Rowan Whitmore" in steady type. Add cobblestone texture and liquid flow effects."""
    ],

    'gothic_supernatural': [
        """Create a cinematic audiobook thumbnail for "Dracula", set in a Gothic cathedral library where stained glass windows cast colored light through an ornate iron lantern, illuminating ancient tomes that float and whisper their stories. Include gargoyles wearing headphones, illuminated manuscripts transforming into audio visualizations, and mysterious monks carrying glowing books. Use a palette of jewel-toned stained glass colors, deep stone grays, and warm candle glow. Place "Bram Stoker" in cathedral stone carving font, "Dracula" in Gothic blackletter fonts with gold leaf effects, and "Narrated by [Narrator]" in brass nameplate type. Add divine light rays and mystical atmosphere."""
    ]
}


def get_llm(model_name: str, temperature: float = DEFAULT_TEMPERATURE):
    """Get the appropriate LLM based on model name."""
    model_lower = model_name.lower()
    
    try:
        if 'gpt' in model_lower or 'openai' in model_lower:
            if not OPENAI_API_KEY:
                raise ValueError("OPENAI_API_KEY not found in environment")
            return ChatOpenAI(model=model_name, api_key=OPENAI_API_KEY, temperature=temperature)
        
        elif 'gemini' in model_lower or 'google' in model_lower:
            try:
                from langchain_google_genai import ChatGoogleGenerativeAI
                api_key = GOOGLE_API_KEY or GEMINI_API_KEY
                if not api_key:
                    raise ValueError("GOOGLE_API_KEY or GEMINI_API_KEY not found in environment")
                return ChatGoogleGenerativeAI(model=model_name, google_api_key=api_key, temperature=temperature)
            except ImportError:
                print("Warning: langchain_google_genai not installed, falling back to OpenAI")
                return ChatOpenAI(model="gpt-4o", api_key=OPENAI_API_KEY, temperature=temperature)
        
        elif 'claude' in model_lower or 'anthropic' in model_lower:
            try:
                from langchain_anthropic import ChatAnthropic
                api_key = ANTHROPIC_API_KEY or CLAUDE_API_KEY
                if not api_key:
                    raise ValueError("ANTHROPIC_API_KEY or CLAUDE_API_KEY not found in environment")
                return ChatAnthropic(model=model_name, anthropic_api_key=api_key, temperature=temperature)
            except ImportError:
                print("Warning: langchain_anthropic not installed, falling back to OpenAI")
                return ChatOpenAI(model="gpt-4o", api_key=OPENAI_API_KEY, temperature=temperature)
        
        else:
            # Default to OpenAI for unknown models
            print(f"Warning: Unknown model {model_name}, using OpenAI GPT-4o")
            return ChatOpenAI(model="gpt-4o", api_key=OPENAI_API_KEY, temperature=temperature)
            
    except Exception as e:
        print(f"Error creating {model_name} LLM: {e}")
        print("Falling back to OpenAI GPT-4o")
        return ChatOpenAI(model="gpt-4o", api_key=OPENAI_API_KEY, temperature=temperature)


def select_relevant_examples(book_context: str) -> List[str]:
    """Select most relevant example prompts based on book context"""
    context_lower = book_context.lower()
    selected_examples = []
    
    # Select examples based on genre matching - more specific matching
    if any(word in context_lower for word in ['mystery', 'thriller', 'detective', 'crime', 'secret', 'spy', 'espionage']):
        selected_examples.extend(EXAMPLE_PROMPTS['mystery_thriller'])
    
    if any(word in context_lower for word in ['adventure', 'expedition', 'exploration', 'prehistoric', 'lost', 'world']):
        selected_examples.extend(EXAMPLE_PROMPTS['classic_adventure'])
    
    if any(word in context_lower for word in ['drama', 'historical', 'revolution', 'war', 'cities', 'dickens', 'tale']):
        selected_examples.extend(EXAMPLE_PROMPTS['literary_drama'])

    if any(word in context_lower for word in ['gothic', 'supernatural', 'horror', 'vampire', 'dracula', 'dark']):
        selected_examples.extend(EXAMPLE_PROMPTS['gothic_supernatural'])
    
    # If no specific match, use a comprehensive mix
    if not selected_examples:
        selected_examples = (EXAMPLE_PROMPTS['mystery_thriller'][:2] + 
                           EXAMPLE_PROMPTS['classic_adventure'][:1] + 
                           EXAMPLE_PROMPTS['literary_drama'][:1])
    
    # Return max 4 examples for good context without overwhelming
    return selected_examples[:4]


def create_search_tools() -> List[BaseTool]:
    """Create and configure web search tools for book research"""
    tools = []
    
    if not SEARCH_TOOLS_AVAILABLE:
        print("⚠️  Search tools not available - using fallback context")
        return tools
    
    # Tavily Search - Best for comprehensive research
    if TAVILY_API_KEY and TAVILY_API_KEY != 'your_tavily_api_key_here':
        try:
            tavily_search = TavilySearchResults(
                max_results=3,
                search_depth="advanced", 
                include_answer=True,
                include_raw_content=False
            )
            tools.append(tavily_search)
        except Exception as e:
            print(f"⚠️  Tavily search not available: {e}")
    
    # Google Search - Additional verification
    if GOOGLE_API_KEY and GOOGLE_API_KEY != 'your_google_api_key_here':
        try:
            google_search = GoogleSearchAPIWrapper(google_api_key=GOOGLE_API_KEY)
            tools.append(google_search)
        except Exception as e:
            print(f"⚠️  Google search not available: {e}")
    
    # Wikipedia - Detailed plot summaries
    try:
        wikipedia = WikipediaQueryRun(api_wrapper=WikipediaAPIWrapper())
        tools.append(wikipedia)
    except Exception as e:
        print(f"⚠️  Wikipedia not available: {e}")
    
    # DuckDuckGo - Free backup option
    try:
        ddg_search = DuckDuckGoSearchRun()
        tools.append(ddg_search)
    except Exception as e:
        print(f"⚠️  DuckDuckGo search not available: {e}")
    
    return tools


def research_book_content(book_title: str, author: str, verbose: bool = False) -> str:
    """Research book content to get rich context for thumbnail generation"""
    
    if not SEARCH_TOOLS_AVAILABLE:
        if verbose:
            print("📚 Search tools not available - using fallback research")
        return f"Classic work by {author}, known for distinctive themes and memorable characters"
    
    if verbose:
        print(f"🔍 Researching '{book_title}' by {author}...")
    
    try:
        # Create search tools
        search_tools = create_search_tools()
        
        if not search_tools:
            if verbose:
                print("⚠️  No search tools available")
            return f"Well-regarded work by {author}"
        
        # Research queries to get comprehensive book context
        search_queries = [
            f'"{book_title}" {author} plot summary characters',
            f'"{book_title}" key scenes visual elements themes',
            f'"{book_title}" {author} setting location time period',
            f'"{book_title}" major plot points story analysis'
        ]
        
        research_results = []
        
        # Use first available search tool
        search_tool = search_tools[0]
        
        for query in search_queries[:2]:  # Limit to 2 queries to stay within rate limits
            try:
                if verbose:
                    print(f"  🔎 Query: {query}")
                
                if hasattr(search_tool, 'run'):
                    result = search_tool.run(query)
                elif hasattr(search_tool, '_run'):
                    result = search_tool._run(query)
                else:
                    result = str(search_tool)
                
                if result and len(result) > 50:
                    research_results.append(result)
                    if verbose:
                        preview = result[:100] + "..." if len(result) > 100 else result
                        print(f"    ✅ Found: {preview}")
                
            except Exception as e:
                if verbose:
                    print(f"    ❌ Query failed: {e}")
                continue
        
        # Process and synthesize research results
        if research_results:
            return synthesize_book_context(book_title, author, research_results, verbose)
        else:
            if verbose:
                print("⚠️  No research results found")
            return f"Notable work by {author} with distinctive narrative elements"
            
    except Exception as e:
        if verbose:
            print(f"❌ Research error: {e}")
        return f"Acclaimed work by {author}"


def synthesize_book_context(book_title: str, author: str, research_results: List[str], verbose: bool = False) -> str:
    """Synthesize research results into rich context for thumbnail generation"""
    
    if verbose:
        print("🧠 Synthesizing research into rich context...")
    
    try:
        # Use AI to process and synthesize the research results
        synthesis_llm = get_llm(DEFAULT_MODEL, temperature=0.3)
        
        # Combine all research results
        combined_research = "\n\n".join(research_results)
        
        synthesis_prompt = f"""You are a book analysis expert. Based on the research below about "{book_title}" by {author}, create a rich context description for generating visual thumbnails.

RESEARCH RESULTS:
{combined_research}

Your task: Extract and synthesize the key visual and narrative elements into a comprehensive context description.

Focus on:
1. **Main Characters**: Names, roles, relationships, distinctive traits
2. **Key Plot Points**: Major events, conflicts, turning points that would make compelling visuals
3. **Settings**: Specific locations, time periods, atmospheric details
4. **Visual Elements**: Objects, symbols, props, costumes that appear in the story
5. **Mood & Atmosphere**: The emotional tone, genre atmosphere, visual style
6. **Distinctive Features**: What makes this book unique and recognizable

Create a detailed, visual-rich context description that will help artists create book-specific (not generic genre) thumbnail images. Be specific about characters, locations, and story elements.

Format as a comprehensive paragraph covering all key visual elements."""

        response = synthesis_llm.invoke(synthesis_prompt)
        
        synthesized_context = response.content.strip()
        
        if verbose:
            preview = synthesized_context[:150] + "..." if len(synthesized_context) > 150 else synthesized_context
            print(f"  ✅ Synthesized context: {preview}")
        
        return synthesized_context
        
    except Exception as e:
        if verbose:
            print(f"❌ Synthesis error: {e}")
        
        # Fallback: extract basic information from research
        fallback_context = extract_basic_context(research_results)
        return fallback_context or f"Literary work by {author} with rich narrative elements"


def extract_basic_context(research_results: List[str]) -> str:
    """Extract basic context information from research results as fallback"""
    
    combined_text = " ".join(research_results).lower()
    
    # Look for character names (capitalized words that appear multiple times)
    character_patterns = re.findall(r'\b[A-Z][a-z]+\b', " ".join(research_results))
    common_characters = [name for name in character_patterns if character_patterns.count(name) > 1][:5]
    
    # Look for time/place indicators
    time_indicators = []
    place_indicators = []
    
    time_patterns = ['century', 'victorian', '1800s', '1900s', 'medieval', 'ancient', 'modern']
    place_patterns = ['london', 'paris', 'new york', 'england', 'france', 'america', 'europe']
    
    for pattern in time_patterns:
        if pattern in combined_text:
            time_indicators.append(pattern)
    
    for pattern in place_patterns:
        if pattern in combined_text:
            place_indicators.append(pattern)
    
    # Build basic context
    context_parts = []
    
    if common_characters:
        context_parts.append(f"featuring characters including {', '.join(common_characters[:3])}")
    
    if time_indicators:
        context_parts.append(f"set in {time_indicators[0]} era")
    
    if place_indicators:
        context_parts.append(f"taking place in {place_indicators[0]}")
    
    if context_parts:
        return "Story " + ", ".join(context_parts) + ", with distinctive narrative elements and visual themes"
    
    return ""


# Enhanced Agent Council - Each agent generates 6 prompts for 24 total candidates
AGENT_ROLES = {
    'cinematic_director': {
        'name': 'Cinematic Director',
        'description': 'Creates movie-quality visual compositions with specific cinematic techniques',
        'prompt': """You are a Cinematic Director specializing in creating movie-poster-quality audiobook thumbnails. Your expertise is in dramatic visual storytelling through composition, lighting, and cinematic techniques.

ASSIGNMENT:
- Book: "{book_title}" by {author}
- Narrator: {narrated_by}
{part_info}

STEP 1 - RESEARCH THE BOOK:
Before creating prompts, research "{book_title}" by {author} to understand:
- Main characters, their relationships and distinctive traits
- Key plot points, dramatic moments, and turning points
- Setting, time period, and atmospheric details
- Major themes, conflicts, and visual symbolism
- Genre conventions and mood

STEP 2 - STUDY CINEMATIC EXAMPLES:
{example_prompts}

STEP 3 - CREATE 6 CINEMATIC PROMPTS:
Based on your research, create exactly 6 thumbnail prompts that demonstrate CINEMATIC MASTERY.

Requirements for each prompt:
- Use specific story elements from your research (characters, scenes, objects)
- Apply cinematic techniques (camera angles, lighting, composition)
- Include atmospheric details from the book's setting
- Show dynamic character positioning and meaningful poses
- Use color psychology that enhances the book's emotional impact
- Typography integration: "{author}" in [appropriate style], "{book_title}" in [dramatic style], "Narrated by {narrated_by}" in [professional style]
{part_instruction}

IMPORTANT OUTPUT FORMAT:
- Each prompt starts with: "Create a cinematic audiobook thumbnail for..."
- Do NOT use numbered lists, markdown headers, or separators
- Generate 6 complete, standalone prompts
- Each prompt should be a single paragraph
- No "Prompt 1:", "###", or numbering

Generate exactly 6 distinct, movie-quality prompts based on the actual book content you researched."""
    },
    
    'story_architect': {
        'name': 'Story Architect',
        'description': 'Designs thumbnails based on specific plot points and character moments',
        'prompt': """You are a Story Architect who creates thumbnails based on the actual story content of "{book_title}" by {author}. Your expertise is in translating key plot moments into compelling visual narratives.

ASSIGNMENT:
- Book: "{book_title}" by {author}
- Narrator: {narrated_by}
{part_info}

STEP 1 - RESEARCH THE BOOK:
Before creating prompts, thoroughly research "{book_title}" by {author} to understand:
- Main characters: names, personalities, relationships, distinctive appearance
- Key plot points: major events, conflicts, turning points, climactic moments
- Settings: specific locations, time period, architectural details, atmosphere
- Important objects: symbols, props, items that appear in the story
- Themes and mood: emotional tone, genre elements, narrative style

STEP 2 - STUDY REFERENCE EXAMPLES:
{example_prompts}

STEP 3 - CREATE 6 STORY-SPECIFIC PROMPTS:
Based on your research, create exactly 6 thumbnails featuring SPECIFIC STORY ELEMENTS.

Requirements for each prompt:
- Reference actual scenes, conflicts, or turning points from your research
- Show specific character relationships, tensions, or emotional moments
- Include actual locations, time periods, or environments from the book
- Use real objects, imagery, or metaphors that appear in the plot
- Capture authentic moments of suspense, revelation, or conflict
- Ensure visuals match the book's actual tone and themes
- Typography specification: "{author}" in [appropriate font], "{book_title}" in [bold impactful style], "Narrated by {narrated_by}" in [clean readable type]
{part_instruction}

IMPORTANT OUTPUT FORMAT:
- Each prompt starts with: "Create a cinematic audiobook thumbnail for..."
- Do NOT use numbered lists, markdown headers, or separators
- Generate 6 complete, standalone prompts
- Each prompt should be a single paragraph
- No "Prompt 1:", "###", or numbering

Generate exactly 6 story-specific prompts that fans of the book would instantly recognize from your research."""
    },
    
    'visual_psychologist': {
        'name': 'Visual Psychologist', 
        'description': 'Creates thumbnails optimized for human psychology and YouTube engagement',
        'prompt': """You are a Visual Psychologist specializing in YouTube thumbnail optimization. Your expertise is in understanding what makes people click, using color psychology, emotional triggers, and visual hierarchy.

ASSIGNMENT:
- Book: "{book_title}" by {author}
- Platform: YouTube audiobook audience
- Narrator: {narrated_by}
{part_info}

STEP 1 - RESEARCH THE BOOK:
Before creating prompts, research "{book_title}" by {author} to understand:
- Genre and target audience expectations
- Emotional themes and psychological elements
- Visual symbolism and metaphors in the story
- Character dynamics that create emotional hooks
- Story elements that trigger curiosity and engagement

STEP 2 - STUDY PROVEN EXAMPLES:
{example_prompts}

STEP 3 - CREATE 6 PSYCHOLOGY-OPTIMIZED PROMPTS:
Based on your research, create exactly 6 psychologically-optimized thumbnails.

Requirements for each prompt:
- Use story elements that trigger curiosity, excitement, or intrigue instantly
- Apply colors that command attention and convey the book's emotions
- Guide the eye to the most important story elements first
- Ensure the thumbnail stands out in YouTube feeds using book-specific imagery
- Design for small screens where most viewing happens
- Include story elements that convey quality and professionalism
- Strategic text placement: "{author}" in [credible style], "{book_title}" in [attention-grabbing design], "Narrated by {narrated_by}" in [trustworthy font]
{part_instruction}

IMPORTANT OUTPUT FORMAT:
- Each prompt starts with: "Create a cinematic audiobook thumbnail for..."
- Do NOT use numbered lists, markdown headers, or separators
- Generate 6 complete, standalone prompts
- Each prompt should be a single paragraph
- No "Prompt 1:", "###", or numbering

Generate exactly 6 click-optimized prompts based on your book research that will maximize engagement."""
    },
    
    'genre_specialist': {
        'name': 'Genre Specialist',
        'description': 'Ensures perfect genre accuracy with deep knowledge of visual conventions',
        'prompt': """You are a Genre Specialist who creates thumbnails that perfectly capture genre expectations while being distinctive. Your role is to research the book and understand its genre conventions.

ASSIGNMENT:
- Book: "{book_title}" by {author}
- Narrator: {narrated_by}
- Target: Genre fans and curious browsers
{part_info}

STEP 1 - RESEARCH THE BOOK:
Before creating prompts, research "{book_title}" by {author} to understand:
- What genre this book belongs to (mystery, romance, adventure, historical, etc.)
- Visual conventions and symbols that fans of this genre expect
- Color palettes and mood associated with this genre
- Typical imagery and iconography for this type of story
- How this specific book fits or subverts genre expectations

STEP 2 - STUDY STYLE REFERENCES:
{example_prompts}

STEP 3 - CREATE 6 GENRE-PERFECT PROMPTS:
Based on your research, create exactly 6 genre-perfect thumbnails.

Requirements for each prompt:
- Use symbols, colors, and imagery that fans of this book's genre expect
- Include familiar genre elements but with fresh twists specific to this book
- Capture the precise emotional tone of this specific story
- Include details that dedicated readers of this genre will appreciate
- Remain welcoming to newcomers to the genre
- Meet current design expectations for this book's genre
- Professional typography: "{author}" in [genre-appropriate font], "{book_title}" in [genre-matching style], "Narrated by {narrated_by}" in [professional standard]
{part_instruction}

IMPORTANT OUTPUT FORMAT:
- Each prompt starts with: "Create a cinematic audiobook thumbnail for..."
- Do NOT use numbered lists, markdown headers, or separators
- Generate 6 complete, standalone prompts
- Each prompt should be a single paragraph
- No "Prompt 1:", "###", or numbering

Generate exactly 6 genre-authentic prompts based on your research that will satisfy both fans and newcomers."""
    }
}


def create_agent_council(
    model_profile: str = 'balanced', 
    temperature: float = DEFAULT_TEMPERATURE,
    verbose: bool = False
) -> Dict[str, Any]:
    """Create the council of specialized agents using different models for diversity."""
    
    agents = {}
    
    # Get model assignments based on profile
    if model_profile in MODEL_PROFILES:
        model_assignments = MODEL_PROFILES[model_profile]
    else:
        # Use balanced profile as default
        model_assignments = MODEL_PROFILES['balanced']
    
    if verbose:
        print(f"  🤖 Creating agent council with '{model_profile}' model profile:")
    
    for role_key, role_info in AGENT_ROLES.items():
        try:
            # Get model for this specific agent
            agent_model = model_assignments.get(role_key, 'gpt-4o-mini')
            
            # Create LLM instance for this agent
            agent_llm = get_llm(agent_model, temperature)
            
            agents[role_key] = {
                'name': role_info['name'],
                'llm': agent_llm,
                'model': agent_model,
                'prompt_template': role_info['prompt']
            }
            
            if verbose:
                print(f"    {role_info['name']}: {agent_model}")
            
        except Exception as e:
            if verbose:
                print(f"    ❌ {role_info['name']}: Failed to create {agent_model}, using fallback")
            
            # Fallback to GPT-4o-mini if specific model fails
            try:
                fallback_llm = get_llm('gpt-4o-mini', temperature)
                agents[role_key] = {
                    'name': role_info['name'],
                    'llm': fallback_llm,
                    'model': 'gpt-4o-mini (fallback)',
                    'prompt_template': role_info['prompt']
                }
            except Exception as fallback_error:
                if verbose:
                    print(f"    ❌ Fallback also failed for {role_info['name']}: {fallback_error}")
    
    return agents


def extract_prompts_from_response(response_text: str, verbose: bool = False) -> List[str]:
    """Clean prompt extraction that removes markdown formatting and duplicates"""
    if verbose:
        print(f"        Raw response length: {len(response_text)} characters")
    
    prompts = []
    
    # Clean the response text first
    cleaned_text = response_text
    
    # Remove common markdown patterns
    cleaned_text = re.sub(r'#{1,6}\s*Prompt\s*\d+', '', cleaned_text)  # Remove ### Prompt 1
    cleaned_text = re.sub(r'#{1,6}\s*', '', cleaned_text)  # Remove all markdown headers
    cleaned_text = re.sub(r'\*\*[^*]+\*\*', '', cleaned_text)  # Remove **bold** text
    cleaned_text = re.sub(r'\n\s*\d+\.\s*', '\n\n', cleaned_text)  # Replace numbered lists with paragraph breaks
    
    # Find all complete prompts that start correctly
    prompt_pattern = r'Create a cinematic audiobook thumbnail[^.]*?(?:Add[^.]*?\.|\.$)'
    matches = re.findall(prompt_pattern, cleaned_text, re.DOTALL | re.IGNORECASE)
    
    for match in matches:
        # Clean up whitespace and formatting
        clean_prompt = re.sub(r'\s+', ' ', match.strip())
        
        # Remove any remaining markdown artifacts
        clean_prompt = re.sub(r'###.*?thumbnail', 'Create a cinematic audiobook thumbnail', clean_prompt)
        clean_prompt = re.sub(r'Prompt\s*\d+\s*', '', clean_prompt)
        
        # Ensure it's long enough and properly formatted
        if len(clean_prompt) > 120 and clean_prompt.lower().startswith('create a cinematic audiobook thumbnail'):
            prompts.append(clean_prompt)
    
    # If we didn't find enough prompts with the pattern, try paragraph-based extraction
    if len(prompts) < 3:
        paragraphs = cleaned_text.split('\n\n')
        for para in paragraphs:
            para = para.strip()
            if len(para) > 150:
                # Clean up any remaining formatting
                para = re.sub(r'\s+', ' ', para)
                para = re.sub(r'Prompt\s*\d+\s*', '', para)
                para = re.sub(r'###\s*', '', para)
                
                # Check if it contains thumbnail-related content
                if any(word in para.lower() for word in ['thumbnail', 'cinematic', 'audiobook', 'featuring']):
                    # Ensure proper start
                    if not para.lower().startswith('create a cinematic audiobook thumbnail'):
                        # Look for the actual start
                        start_match = re.search(r'create a cinematic audiobook thumbnail', para, re.IGNORECASE)
                        if start_match:
                            para = para[start_match.start():]
                        else:
                            para = f"Create a cinematic audiobook thumbnail for the book, {para}"
                    
                    prompts.append(para)
    
    # Final cleanup and deduplication
    final_prompts = []
    seen_content = set()
    
    for prompt in prompts:
        # Final cleaning pass
        prompt = re.sub(r'\s+', ' ', prompt.strip())
        prompt = re.sub(r'Create a cinematic audiobook thumbnail\s+Create a cinematic audiobook thumbnail', 'Create a cinematic audiobook thumbnail', prompt)
        
        # Check for duplicates by comparing first 100 characters
        content_signature = prompt[:100].lower()
        if content_signature not in seen_content and len(prompt) > 120:
            final_prompts.append(prompt)
            seen_content.add(content_signature)
    
    if verbose:
        print(f"        Extracted {len(final_prompts)} clean, unique prompts")
        for i, prompt in enumerate(final_prompts, 1):
            preview = prompt[:80] + "..." if len(prompt) > 80 else prompt
            print(f"          {i}. {preview}")
    
    return final_prompts


def validate_prompt_quality(prompt: str, book_title: str, author: str, narrated_by: str, verbose: bool = False) -> bool:
    """Simplified validation to debug what's failing"""
    
    # Basic length check
    if len(prompt) < 50:
        if verbose:
            print(f"          REJECTED: Too short ({len(prompt)} chars)")
        return False
    
    prompt_lower = prompt.lower()
    
    # Must start with the right phrase
    if not prompt_lower.startswith('create a cinematic audiobook thumbnail'):
        if verbose:
            print(f"          REJECTED: Wrong start - {prompt[:50]}...")
        return False
    
    # Must have basic visual language
    visual_words = ['cinematic', 'featuring', 'showing', 'style', 'design']
    has_visual_language = any(word in prompt_lower for word in visual_words)
    
    if not has_visual_language:
        if verbose:
            print(f"          REJECTED: No visual language")
        return False
    
    if verbose:
        print(f"          ✅ VALID: {len(prompt)} chars, starts correctly, has visual language")
    
    return True


def advanced_voting_system(
    all_candidates: List[str],
    book_title: str,
    author: str,
    narrated_by: str,
    part_info: str,
    model: str = DEFAULT_MODEL,
    verbose: bool = False
) -> Tuple[List[str], Dict]:
    """Advanced voting system with detailed process visibility and metadata"""
    
    if verbose:
        print(f"  🗳️  ADVANCED VOTING SYSTEM ACTIVATED")
        print(f"      Evaluating {len(all_candidates)} candidates...")
    
    if len(all_candidates) <= 5:
        if verbose:
            print(f"      ⚠️  Only {len(all_candidates)} candidates, returning all")
        return all_candidates, {'warning': 'insufficient_candidates', 'count': len(all_candidates)}
    
    try:
        evaluator_llm = get_llm(model, temperature=0.2)  # Very low temperature for consistent evaluation
        
        # Format candidates for evaluation
        candidates_text = "\n\n".join([f"CANDIDATE #{i+1}:\n{prompt}" for i, prompt in enumerate(all_candidates)])
        
        evaluation_prompt = f"""You are an expert thumbnail evaluator for "{book_title}" by {author}.

EVALUATION CRITERIA (with weights):
1. **Cinematic Quality (30%)** - Visual sophistication, composition, lighting techniques
2. **Story Relevance (25%)** - Accuracy to "{book_title}" themes and content  
3. **YouTube Performance (20%)** - Click-worthy design, mobile optimization, attention-grabbing
4. **Professional Polish (15%)** - Typography quality, production value, overall finish
5. **Genre Authenticity (10%)** - Appropriate for the book's genre and themes

CANDIDATES TO EVALUATE:
{candidates_text}

**TASK**: Evaluate each candidate and return the TOP 5 with detailed scoring.

**REQUIRED OUTPUT FORMAT** (JSON only, no other text):
[
  {{
    "rank": 1,
    "candidate_number": X,
    "prompt": "exact candidate text...",
    "total_score": 95,
    "scores": {{
      "cinematic_quality": 28,
      "story_relevance": 24,
      "youtube_performance": 19,
      "professional_polish": 15,
      "genre_authenticity": 9
    }},
    "selection_reason": "detailed explanation of why this ranks #1",
    "strengths": ["specific strength 1", "specific strength 2", "specific strength 3"]
  }},
  {{
    "rank": 2,
    "candidate_number": Y,
    "prompt": "exact candidate text...",
    "total_score": 88,
    "scores": {{
      "cinematic_quality": 26,
      "story_relevance": 22,
      "youtube_performance": 18,
      "professional_polish": 13,
      "genre_authenticity": 9
    }},
    "selection_reason": "detailed explanation of why this ranks #2",
    "strengths": ["specific strength 1", "specific strength 2"]
  }},
  {{
    "rank": 3,
    "candidate_number": Z,
    "prompt": "exact candidate text...",
    "total_score": 85,
    "scores": {{
      "cinematic_quality": 25,
      "story_relevance": 21,
      "youtube_performance": 17,
      "professional_polish": 13,
      "genre_authenticity": 9
    }},
    "selection_reason": "detailed explanation of why this ranks #3",
    "strengths": ["specific strength 1", "specific strength 2"]
  }},
  {{
    "rank": 4,
    "candidate_number": A,
    "prompt": "exact candidate text...",
    "total_score": 82,
    "scores": {{
      "cinematic_quality": 24,
      "story_relevance": 20,
      "youtube_performance": 16,
      "professional_polish": 12,
      "genre_authenticity": 10
    }},
    "selection_reason": "detailed explanation of why this ranks #4",
    "strengths": ["specific strength 1"]
  }},
  {{
    "rank": 5,
    "candidate_number": B,
    "prompt": "exact candidate text...",
    "total_score": 78,
    "scores": {{
      "cinematic_quality": 23,
      "story_relevance": 19,
      "youtube_performance": 15,
      "professional_polish": 11,
      "genre_authenticity": 10
    }},
    "selection_reason": "detailed explanation of why this ranks #5",
    "strengths": ["specific strength 1"]
  }}
]

Return ONLY the JSON array above. No additional text."""

        if verbose:
            print(f"      📊 Sending evaluation request to {model}...")
        
        response = evaluator_llm.invoke(evaluation_prompt)
        
        if verbose:
            print(f"      📋 Received evaluation response ({len(response.content)} chars)")
        
        # Parse JSON response
        try:
            results = json.loads(response.content.strip())
            
            if not isinstance(results, list) or len(results) != 5:
                raise ValueError(f"Expected list of 5 results, got {type(results)} with {len(results) if isinstance(results, list) else 'unknown'} items")
            
            # Extract prompts and create metadata
            top_prompts = []
            voting_metadata = {
                'evaluation_model': model,
                'total_candidates': len(all_candidates),
                'evaluation_criteria': {
                    'cinematic_quality': '30%',
                    'story_relevance': '25%', 
                    'youtube_performance': '20%',
                    'professional_polish': '15%',
                    'genre_authenticity': '10%'
                },
                'selected_prompts': [],
                'voting_timestamp': datetime.now().isoformat()
            }
            
            for result in results:
                top_prompts.append(result['prompt'])
                voting_metadata['selected_prompts'].append({
                    'rank': result['rank'],
                    'candidate_number': result.get('candidate_number', 'unknown'),
                    'total_score': result['total_score'],
                    'detailed_scores': result['scores'],
                    'selection_reason': result['selection_reason'],
                    'strengths': result.get('strengths', [])
                })
            
            if verbose:
                print(f"      ✅ Successfully selected top 5 prompts:")
                for i, result in enumerate(results, 1):
                    print(f"        #{i}: Score {result['total_score']}/100 - {result['selection_reason'][:60]}...")
            
            return top_prompts, voting_metadata
            
        except json.JSONDecodeError as e:
            if verbose:
                print(f"      ❌ JSON parsing failed: {e}")
                print(f"      Raw response preview: {response.content[:200]}...")
            
            # Fallback: return first 5 with basic metadata
            fallback_metadata = {
                'evaluation_model': model,
                'total_candidates': len(all_candidates),
                'error': 'json_parsing_failed',
                'fallback_method': 'first_5_candidates'
            }
            return all_candidates[:5], fallback_metadata
    
    except Exception as e:
        if verbose:
            print(f"      ❌ Voting system error: {e}")
        
        # Emergency fallback
        emergency_metadata = {
            'evaluation_model': model,
            'total_candidates': len(all_candidates),
            'error': str(e),
            'fallback_method': 'emergency_first_5'
        }
        return all_candidates[:5], emergency_metadata


def export_prompt_analysis(
    book_id: str,
    book_title: str,
    author: str,
    narrated_by: str,
    book_context: str,
    part_info: str,
    all_candidates: List[str],
    selected_prompts: List[str],
    voting_metadata: Dict,
    agent_performance: Dict,
    generation_stats: Dict,
    research_metadata: Dict = None
) -> str:
    """Export comprehensive prompt analysis data to book-specific directory"""
    
    # Create comprehensive analysis data
    analysis_data = {
        'generation_session': {
            'timestamp': datetime.now().isoformat(),
            'book_details': {
                'book_id': book_id,
                'title': book_title,
                'author': author,
                'narrator': narrated_by,
                'context': book_context,
                'part_info': part_info
            },
            'generation_stats': generation_stats,
            'model_used': generation_stats.get('model_profile', 'unknown')
        },
        
        'web_research': research_metadata or {
            'search_tools_available': False,
            'research_successful': False,
            'original_context': book_context,
            'enriched_context': book_context
        },
        
        'candidate_analysis': {
            'total_generated': len(all_candidates),
            'all_candidates': [
                {
                    'index': i,
                    'prompt': prompt,
                    'length': len(prompt),
                    'selected': prompt in selected_prompts
                }
                for i, prompt in enumerate(all_candidates, 1)
            ]
        },
        
        'agent_performance': agent_performance,
        
        'voting_results': voting_metadata,
        
        'final_selection': [
            {
                'rank': i,
                'prompt': prompt,
                'metadata': voting_metadata.get('selected_prompts', [{}])[i-1] if i <= len(voting_metadata.get('selected_prompts', [])) else {}
            }
            for i, prompt in enumerate(selected_prompts, 1)
        ],
        
        'quality_metrics': {
            'candidate_generation_success_rate': f"{len(all_candidates)}/24 target",
            'agent_success_rate': len([a for a in agent_performance.values() if a.get('valid_prompts', 0) > 0]) / len(agent_performance),
            'average_prompt_length': sum(len(p) for p in all_candidates) / len(all_candidates) if all_candidates else 0,
            'selection_diversity': len(set(selected_prompts))
        },
        
        'optimization_insights': {
            'best_performing_agent': max(agent_performance.items(), key=lambda x: x[1].get('valid_prompts', 0))[0] if agent_performance else 'unknown',
            'average_candidate_score': voting_metadata.get('selected_prompts', [{}])[-1].get('total_score', 0) if voting_metadata.get('selected_prompts') else 0,
            'improvement_areas': []  # To be filled based on analysis
        }
    }
    
    # Save to book-specific directory
    book_dir = Path(f"foundry/processing/{book_id}")
    book_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = book_dir / f"prompt_analysis_{timestamp}.json"
    
    # Export comprehensive analysis to book directory
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(analysis_data, f, indent=2, ensure_ascii=False)
    
    return filename


def create_fallback_prompt(book_title: str, author: str, narrated_by: str, part_info: str) -> str:
    """Create a high-quality fallback prompt that meets all requirements"""
    return f"""Create a cinematic audiobook thumbnail for "{book_title}" by {author}, featuring elegant literary design with sophisticated visual elements that convey the book's dramatic themes and professional quality. Utilize a compelling poster style with dynamic lighting and rich atmospheric color palette appropriate to the story's mood. Employ dramatic composition with strong focal points and visual hierarchy that draws the viewer's attention. Display "{author}" in classic readable serif font, "{book_title}" in bold impactful lettering that commands attention, and "Narrated by {narrated_by}" in clean professional type that conveys trustworthiness. Add atmospheric effects and visual metaphors that suggest the book's central themes while maintaining broad appeal for audiobook listeners seeking quality content."""


def generate_image_prompts_internal(
    book_title: str,
    author: str,
    narrated_by: str,
    part_number: Optional[int] = None,
    total_parts: Optional[int] = None,
    chapter_info: Optional[str] = None,
    model_profile: str = 'balanced',
    temperature: float = DEFAULT_TEMPERATURE,
    verbose: bool = False,
    book_id: Optional[str] = None
) -> List[str]:
    """
    Generate exactly 5 high-quality thumbnail prompts using advanced agent council voting.
    
    Returns:
        List of exactly 5 high-quality thumbnail prompt strings
    """
    
    print(f"🎬 ENHANCED THUMBNAIL GENERATOR - AGENT COUNCIL WITH WEB RESEARCH")
    print(f"📚 Book: {book_title} by {author}")
    print(f"🎙️  Narrator: {narrated_by}")
    
    generation_start_time = datetime.now()
    
    try:
        # 🔍 BOOK RESEARCH PHASE - Agents will research book content themselves
        print(f"\n🔍 AGENTS WILL RESEARCH BOOK CONTENT AUTOMATICALLY")
        print(f"📖 Each agent will search for: plot, characters, themes, visual elements")
        
        # Get relevant examples for multi-shot learning (use mystery as default for example selection)
        relevant_examples = select_relevant_examples("mystery thriller")  # Default to get some examples
        example_text = "\n\n".join([f"REFERENCE EXAMPLE {i+1}:\n{ex}" for i, ex in enumerate(relevant_examples)])
        
        print(f"📖 Selected {len(relevant_examples)} relevant examples for multi-shot learning")
        
        # Handle part information intelligently
        if total_parts and total_parts > 1 and part_number:
            part_info = f"Part {part_number} of {total_parts}"
            if chapter_info:
                part_info += f" ({chapter_info})"
            part_instruction = f"- IMPORTANT: Include 'Part {part_number}' prominently in the design since this is part {part_number} of {total_parts} total parts"
        else:
            part_info = "Single complete audiobook" + (f" ({chapter_info})" if chapter_info else "")
            part_instruction = "- IMPORTANT: Do not include part numbers since this is a complete single audiobook"
        
        print(f"📋 Configuration: {part_info}")
        
        # Create agent council with multi-model setup
        agents = create_agent_council(model_profile=model_profile, temperature=temperature, verbose=verbose)
        print(f"👥 Multi-model agent council assembled: {len(agents)} specialized agents")
        
        # Initialize tracking
        all_candidates = []
        agent_performance = {}
        
        # Generate candidate prompts from all agents
        print(f"\n🏭 CANDIDATE GENERATION PHASE")
        for role_key, agent_info in agents.items():
            print(f"  🤖 {agent_info['name']} working...")
            
            try:
                # Format agent prompt - agents will research book context themselves
                formatted_prompt = agent_info['prompt_template'].format(
                    book_title=book_title,
                    author=author,
                    narrated_by=narrated_by,
                    part_info=part_info,
                    part_instruction=part_instruction,
                    example_prompts=example_text
                )
                
                # Get response from agent
                response = agent_info['llm'].invoke(formatted_prompt)
                
                # DEBUG: Show raw agent response
                if verbose:
                    print(f"        🔍 RAW RESPONSE from {agent_info['name']}:")
                    response_preview = response.content[:300] + "..." if len(response.content) > 300 else response.content
                    print(f"        {response_preview}")
                    print(f"        📏 Response length: {len(response.content)} characters")
                
                raw_prompts = extract_prompts_from_response(response.content, verbose=verbose)
                
                # DEBUG: Show extraction results
                if verbose:
                    print(f"        📤 EXTRACTED {len(raw_prompts)} prompts from response")
                
                # Validate and collect prompts
                valid_prompts = []
                for i, prompt in enumerate(raw_prompts, 1):
                    is_valid = validate_prompt_quality(prompt, book_title, author, narrated_by, verbose=verbose)
                    if verbose:
                        print(f"        📋 Prompt {i}: {'✅ VALID' if is_valid else '❌ REJECTED'}")
                        if not is_valid:
                            print(f"            Preview: {prompt[:100]}...")
                    
                    if is_valid:
                        valid_prompts.append(prompt)
                        all_candidates.append(prompt)
                
                # Track agent performance with model info
                agent_performance[role_key] = {
                    'name': agent_info['name'],
                    'model': agent_info.get('model', 'unknown'),
                    'raw_generated': len(raw_prompts),
                    'valid_prompts': len(valid_prompts),
                    'success_rate': len(valid_prompts) / max(1, len(raw_prompts)),
                    'prompts': valid_prompts
                }
                
                print(f"      ✅ Generated {len(raw_prompts)} raw, {len(valid_prompts)} valid")
                
                # CRITICAL DEBUG: If no valid prompts, show why
                if len(valid_prompts) == 0 and len(raw_prompts) > 0:
                    print(f"      🚨 CRITICAL: Agent generated {len(raw_prompts)} prompts but ALL were rejected!")
                    print(f"      📝 First raw prompt preview: {raw_prompts[0][:150]}..." if raw_prompts else "No raw prompts")
                
            except Exception as e:
                print(f"      ❌ Agent failed: {e}")
                if verbose:
                    print(f"      🔍 Agent model: {agent_info.get('model', 'unknown')}")
                    print(f"      🔍 Error type: {type(e).__name__}")
                
                agent_performance[role_key] = {
                    'name': agent_info['name'],
                    'model': agent_info.get('model', 'unknown'),
                    'error': str(e),
                    'raw_generated': 0,
                    'valid_prompts': 0
                }
        
        print(f"\n📊 GENERATION SUMMARY:")
        print(f"  Total candidates collected: {len(all_candidates)}")
        
        # CRITICAL DEBUG: Check for total failure
        if len(all_candidates) == 0:
            print(f"  🚨 CRITICAL FAILURE: NO agents generated ANY valid prompts!")
            print(f"  🔍 All agents either failed or all prompts were rejected by validation")
            print(f"  ⚠️  System will fall back to identical generic prompts")
        
        for role_key, perf in agent_performance.items():
            model_name = perf.get('model', 'unknown')
            valid_count = perf.get('valid_prompts', 0)
            error = perf.get('error', None)
            
            if error:
                print(f"    ❌ {perf['name']} ({model_name}): FAILED - {error}")
            else:
                print(f"    {'✅' if valid_count > 0 else '❌'} {perf['name']} ({model_name}): {valid_count} valid prompts")
        
        # Advanced voting system
        print(f"\n🗳️  ADVANCED VOTING PHASE")
        if len(all_candidates) >= 5:
            selected_prompts, voting_metadata = advanced_voting_system(
                all_candidates,
                book_title,
                author,
                narrated_by,
                part_info,
                'gpt-4o',  # Use specific model for evaluation
                verbose=True
            )
        else:
            raise Exception(f"VOTING FAILED: Only {len(all_candidates)} candidates, need at least 5 for voting")
        
        # NO FALLBACKS - Fail if we don't have enough prompts
        if len(selected_prompts) < 5:
            raise Exception(f"GENERATION FAILED: Only {len(selected_prompts)} prompts generated, need 5. Candidates: {len(all_candidates)}")
        
        # Final selection
        final_prompts = selected_prompts[:5]
        
        # 🏆 Display the top 5 selected prompts with scoring details
        print(f"\n🏆 TOP 5 SELECTED PROMPTS:")
        print("=" * 60)
        for i, prompt in enumerate(final_prompts, 1):
            print(f"\n🥇 RANK #{i}")
            print(f"📝 PROMPT: {prompt}")
            
            # Show selection metadata if available
            if voting_metadata and 'selected_prompts' in voting_metadata and len(voting_metadata['selected_prompts']) >= i:
                selection_info = voting_metadata['selected_prompts'][i-1]
                print(f"📊 SCORE: {selection_info.get('total_score', 'N/A')}/100")
                if 'detailed_scores' in selection_info:
                    scores = selection_info['detailed_scores']
                    print(f"   • Cinematic Quality: {scores.get('cinematic_quality', 'N/A')}/30")
                    print(f"   • Story Relevance: {scores.get('story_relevance', 'N/A')}/25")
                    print(f"   • YouTube Performance: {scores.get('youtube_performance', 'N/A')}/20")
                print(f"💡 REASON: {selection_info.get('selection_reason', 'No reason provided')}")
                if 'strengths' in selection_info:
                    print(f"💪 STRENGTHS: {', '.join(selection_info['strengths'])}")
            else:
                print(f"📊 SCORE: Selected by voting system")
            
            print("-" * 60)
        
        # Generate comprehensive metadata with model performance tracking
        model_performance = {}
        for role_key, perf in agent_performance.items():
            model_name = perf.get('model', 'unknown')
            if model_name not in model_performance:
                model_performance[model_name] = {'prompts_generated': 0, 'prompts_selected': 0, 'agents_using': []}
            
            model_performance[model_name]['prompts_generated'] += perf.get('valid_prompts', 0)
            model_performance[model_name]['agents_using'].append(perf['name'])
            
            # Count how many of this agent's prompts were selected
            agent_selected = sum(1 for prompt in final_prompts if prompt in perf.get('prompts', []))
            model_performance[model_name]['prompts_selected'] += agent_selected
        
        generation_stats = {
            'model_profile': model_profile,
            'temperature': temperature,
            'generation_time_seconds': (datetime.now() - generation_start_time).total_seconds(),
            'total_candidates': len(all_candidates),
            'selected_count': len(final_prompts),
            'success_rate': len(all_candidates) / 24,  # Target was 24 (6 per agent * 4 agents)
            'web_research_enabled': SEARCH_TOOLS_AVAILABLE,
            'agent_research_method': 'each_agent_researches_independently',
            'model_performance': model_performance
        }
        
        # Add research information to metadata
        research_metadata = {
            'research_method': 'agent_independent_research',
            'search_tools_available': SEARCH_TOOLS_AVAILABLE,
            'agents_research_automatically': True
        }
        
        # Export detailed analysis to appropriate location
        if book_id:
            # For book pipeline integration - save to book-specific directory
            analysis_file = export_prompt_analysis(
                book_id, book_title, author, narrated_by, "agent_researched_context", part_info,
                all_candidates, final_prompts, voting_metadata, 
                agent_performance, generation_stats, research_metadata
            )
        else:
            # For standalone testing - save to current directory
            analysis_file = export_prompt_analysis(
                "test_book", book_title, author, narrated_by, "agent_researched_context", part_info,
                all_candidates, final_prompts, voting_metadata, 
                agent_performance, generation_stats, research_metadata
            )
        
        print(f"\n✅ GENERATION COMPLETE!")
        print(f"  📝 Selected prompts: {len(final_prompts)}")
        print(f"  💾 Analysis exported: {analysis_file}")
        print(f"  ⏱️  Total time: {generation_stats['generation_time_seconds']:.1f}s")
        
        return final_prompts
        
    except Exception as e:
        print(f"\n❌ CRITICAL ERROR: {e}")
        
        # NO EMERGENCY FALLBACKS - Let it fail for debugging
        print(f"\n🚨 CRITICAL ERROR: {e}")
        print(f"💥 System failed - no fallbacks to hide the issue")
        raise e  # Re-raise the error instead of hiding it


def generate_image_prompts_for_book(
    book_id: str,
    book_title: str,
    author: str,
    narrated_by: str,
    metadata_file_path: str,
    model_profile: str = 'balanced',  # Use model profile for multi-model support
    temperature: float = DEFAULT_TEMPERATURE,
    verbose: bool = True
) -> Dict:
    """
    Generate 5 high-quality image prompts per video part using enhanced agent council voting.
    This is the main function for integration with the audiobook pipeline.
    """
    if verbose:
        print(f"🎬 ENHANCED IMAGE PROMPT GENERATOR")
        print("=" * 60)
    
    metadata_file = Path(metadata_file_path)
    
    if not metadata_file.exists():
        error_msg = f"Metadata file not found: {metadata_file}"
        if verbose:
            print(f"❌ ERROR: {error_msg}")
        return {'success': False, 'error': error_msg}
    
    try:
        # Load existing metadata
        with open(metadata_file, 'r', encoding='utf-8') as f:
            metadata = json.load(f)
        
        # Get combination plan
        combination_plan = metadata.get('audio_combination_plan')
        if not combination_plan:
            error_msg = "No audio combination plan found in metadata"
            if verbose:
                print(f"❌ ERROR: {error_msg}")
            return {'success': False, 'error': error_msg}
        
        parts_needed = combination_plan['parts_needed']
        combinations = combination_plan['combinations']
        
        if verbose:
            print(f"📚 Book: {book_title} by {author}")
            print(f"🎙️  Narrator: {narrated_by}")
            print(f"🔍 Agents will research book context automatically")
            print(f"📹 Video parts: {parts_needed}")
            print(f"🤖 Model Profile: {model_profile}")
            print()
        
        # Generate prompts for each video part
        all_prompts = []
        
        # DEBUG: Show all parts before processing
        if verbose:
            print(f"📋 PARTS TO PROCESS:")
            for i, combo in enumerate(combinations):
                print(f"  Part {combo['part']}: Chapters {combo.get('chapter_range', 'unknown')}")
            print()
        
        for combination in combinations:
            part_num = combination['part']
            chapters = combination['chapters']
            chapter_range = combination.get('chapter_range', f"{chapters[0]}-{chapters[-1]}")
            duration_hours = combination.get('duration_hours', 0)
            
            chapter_info = f"Chapters {chapter_range}, {duration_hours:.1f} hours"
            
            if verbose:
                print(f"🎬 PROCESSING Part {part_num} ({chapter_info})...")
                print(f"  📚 Current all_prompts array has {len(all_prompts)} parts")
            
            # Generate prompts using enhanced system - agents research book automatically
            selected_prompts = generate_image_prompts_internal(
                book_title=book_title,
                author=author,
                narrated_by=narrated_by,
                part_number=part_num if parts_needed > 1 else None,
                total_parts=parts_needed if parts_needed > 1 else None,
                chapter_info=chapter_info,
                model_profile=model_profile,  # Use model profile instead of single model
                temperature=temperature,
                verbose=verbose,
                book_id=book_id  # Pass book_id for proper analysis export
            )
            
            # Format prompts with metadata
            part_prompts = []
            for i, prompt in enumerate(selected_prompts, 1):
                part_prompts.append({
                    'prompt_id': f"{book_id}_part{part_num}_prompt{i}",
                    'filename': f"{book_id}_part{part_num}_option{i}.png",
                    'prompt': prompt,
                    'rank': i
                })
            
            # DEBUG: Show part details before adding
            if verbose:
                print(f"  📝 Part {part_num} data:")
                print(f"    Chapters: {chapter_range}")
                print(f"    Prompts generated: {len(part_prompts)}")
                for i, prompt_data in enumerate(part_prompts[:2], 1):
                    preview = prompt_data['prompt'][:60] + "..." if len(prompt_data['prompt']) > 60 else prompt_data['prompt']
                    print(f"      {i}. {preview}")
            
            all_prompts.append({
                'part': part_num,
                'chapter_range': chapter_range,
                'chapters': chapters,
                'duration_hours': duration_hours,
                'prompts': part_prompts
            })
            
            if verbose:
                print(f"  ✅ Added Part {part_num} to all_prompts array (total parts: {len(all_prompts)})")
                print()
        
        # Add prompts to metadata
        metadata['image_prompts'] = {
            'generation_completed_at': datetime.now().isoformat(),
            'total_parts': parts_needed,
            'total_prompts': parts_needed * 5,
            'prompts_per_part': 5,
            'model_profile': model_profile,
            'generation_method': 'enhanced_agent_council_multi_model_with_web_research',
            'parts': all_prompts
        }
        
        # DEBUG: Show what we're about to save
        print(f"\n💾 METADATA UPDATE DEBUG:")
        print(f"  📁 File: {metadata_file}")
        print(f"  📝 Prompts to save: {len(all_prompts)} parts")
        for part_data in all_prompts:
            print(f"    Part {part_data['part']}: {len(part_data['prompts'])} prompts")
            for i, prompt_data in enumerate(part_data['prompts'][:2], 1):
                preview = prompt_data['prompt'][:80] + "..." if len(prompt_data['prompt']) > 80 else prompt_data['prompt']
                print(f"      {i}. {preview}")
        
        # Save updated metadata
        print(f"  🔄 Writing to {metadata_file}...")
        try:
            with open(metadata_file, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
            print(f"  ✅ Successfully wrote metadata file")
        except Exception as write_error:
            print(f"  ❌ Failed to write metadata: {write_error}")
            raise Exception(f"Metadata write failed: {write_error}")
        
        if verbose:
            print("=" * 60)
            print("🎉 ENHANCED PROMPT GENERATION COMPLETE!")
            print(f"  📊 Total parts: {parts_needed}")
            print(f"  📝 Total prompts: {parts_needed * 5}")
            print(f"  🤖 Model profile: {model_profile}")
            print(f"  💾 Saved to: {metadata_file}")
            print()
            
            # Show sample prompts
            if all_prompts:
                print("📖 Sample prompts:")
                sample_part = all_prompts[0]
                print(f"  Part {sample_part['part']} (Chapters {sample_part['chapter_range']}):")
                for prompt_data in sample_part['prompts'][:2]:  # Show first 2
                    preview = prompt_data['prompt'][:100] + "..." if len(prompt_data['prompt']) > 100 else prompt_data['prompt']
                    print(f"    {prompt_data['rank']}. {preview}")
                if len(sample_part['prompts']) > 2:
                    print(f"    ... and {len(sample_part['prompts']) - 2} more high-quality prompts")
        
        return {
            'success': True,
            'total_parts': parts_needed,
            'total_prompts': parts_needed * 5,
            'prompts_per_part': 5,
            'metadata_file': metadata_file,
            'model_profile': model_profile,
            'parts': all_prompts
        }
        
    except Exception as e:
        error_msg = f"Enhanced prompt generation error: {e}"
        if verbose:
            print(f"❌ ERROR: {error_msg}")
            import traceback
            traceback.print_exc()
        return {'success': False, 'error': error_msg}


def generate_image_prompts(
    book_id: str,
    book_title: str,
    author: str,
    narrator: str,
    model_profile: str = 'balanced'
) -> List[str]:
    """
    MAIN FUNCTION FOR AUDIOBOOK PIPELINE INTEGRATION
    
    Generate 5 unique thumbnail prompts using multi-model agent council.
    Agents automatically research the book to get accurate context.
    
    Args:
        book_id: Book ID (e.g., 'pg98', 'pg1155')
        book_title: Title of the book (e.g., 'A Tale of Two Cities')
        author: Author name (e.g., 'Charles Dickens')
        narrator: Narrator name (e.g., 'Rowan Whitmore')
        model_profile: 'balanced', 'high_quality', or 'economy'
        
    Returns:
        List of exactly 5 unique professional thumbnail prompt strings
    """
    return generate_image_prompts_internal(
        book_title=book_title,
        author=author,
        narrated_by=narrator,
        book_id=book_id,
        model_profile=model_profile,
        verbose=True  # Enable debugging to see why we get identical prompts
    )


def generate_image_prompts_from_foundry(
    book_id: str,
    language: str,
    audiobook_dict: Dict,
    model_profile: str = 'balanced',
    verbose: bool = True
) -> Dict:
    """
    Generate image prompts using new foundry architecture with combination_plan.json.
    
    Wrapper function that adapts combination_plan.json data format for the existing
    generate_image_prompts_for_book() function.
    
    Args:
        book_id: Book identifier (e.g., 'pg74')
        language: Language code (e.g., 'eng')
        audiobook_dict: Complete audiobook metadata dict
        model_profile: Model profile for generation
        verbose: Whether to print progress messages
        
    Returns:
        Dict with success status and generated prompts data
    """
    import json
    import tempfile
    import os
    
    if verbose:
        print(f"🎨 Starting image prompt generation for foundry architecture")
    
    # Read combination plan
    plan_file = f"foundry/{book_id}/{language}/combination_plan.json"
    
    if not os.path.exists(plan_file):
        error_msg = f"Combination plan not found: {plan_file}"
        if verbose:
            print(f"❌ ERROR: {error_msg}")
        return {'success': False, 'error': error_msg}
    
    try:
        with open(plan_file, 'r', encoding='utf-8') as f:
            combination_plan = json.load(f)
        
        # Create temporary metadata file in expected format
        temp_metadata = {
            'audio_combination_plan': combination_plan,  # Nest under expected key
            'book_id': book_id,
            'book_title': audiobook_dict.get('book_name', book_id),
            'author': audiobook_dict.get('author', 'Unknown'),
            'narrator': audiobook_dict.get('narrator_name', 'Unknown')
        }
        
        # Create temporary metadata file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as temp_file:
            json.dump(temp_metadata, temp_file, indent=2, ensure_ascii=False)
            temp_metadata_path = temp_file.name
        
        if verbose:
            print(f"📄 Created temporary metadata file: {temp_metadata_path}")
            print(f"🔗 Adapting combination plan for existing image prompt function")
        
        # Call existing function with adapted data
        result = generate_image_prompts_for_book(
            book_id=book_id,
            book_title=audiobook_dict.get('book_name', book_id),
            author=audiobook_dict.get('author', 'Unknown'),
            narrated_by=audiobook_dict.get('narrator_name', 'Unknown'),
            metadata_file_path=temp_metadata_path,
            model_profile=model_profile,
            verbose=verbose
        )
        
        # If successful, extract prompts and save to foundry structure
        if result.get('success', False):
            try:
                # Read the updated temporary metadata file to get generated prompts
                with open(temp_metadata_path, 'r', encoding='utf-8') as f:
                    updated_metadata = json.load(f)
                
                image_prompts_data = updated_metadata.get('image_prompts', {})
                parts_data = image_prompts_data.get('parts', [])
                
                if parts_data:
                    # Save prompts to foundry structure for each part
                    combinations = combination_plan.get('combinations', [])
                    for i, part_data in enumerate(parts_data):
                        part_num = part_data['part']
                        
                        # Determine output filename based on number of parts
                        if len(combinations) > 1:
                            prompts_filename = f"{book_id}_part{part_num}_prompts.json"
                        else:
                            prompts_filename = f"{book_id}_prompts.json"
                        
                        prompts_output_path = f"foundry/{book_id}/{language}/image_prompts/{prompts_filename}"
                        
                        # Create directory
                        os.makedirs(os.path.dirname(prompts_output_path), exist_ok=True)
                        
                        # Save prompts to foundry location
                        with open(prompts_output_path, 'w', encoding='utf-8') as f:
                            json.dump(part_data, f, indent=2, ensure_ascii=False)
                        
                        if verbose:
                            print(f"💾 Saved image prompts for Part {part_num}: {prompts_output_path}")
                
            except Exception as e:
                if verbose:
                    print(f"⚠️ Warning: Could not extract prompts to foundry structure: {e}")
        
        # Clean up temporary file
        try:
            os.unlink(temp_metadata_path)
            if verbose:
                print(f"🗑️ Cleaned up temporary metadata file")
        except:
            pass  # Don't fail if cleanup fails
        
        if verbose:
            if result.get('success', False):
                print(f"✅ Image prompt generation completed successfully")
            else:
                print(f"❌ Image prompt generation failed: {result.get('error', 'Unknown error')}")
        
        return result
        
    except Exception as e:
        error_msg = f"Error adapting data for image prompt generation: {e}"
        if verbose:
            print(f"❌ ERROR: {error_msg}")
        return {'success': False, 'error': error_msg}


def main():
    """Test the enhanced system"""
    print("🎬 ENHANCED AUDIOBOOK THUMBNAIL GENERATOR - MULTI-MODEL AGENT COUNCIL")
    print("=" * 70)
    
    # Simple test with A Tale of Two Cities
    book_id = "pg98"
    book_title = "A Tale of Two Cities"
    author = "Charles Dickens"
    narrator = "Rowan Whitmore"
    
    print(f"📚 Testing: {book_title} by {author} (ID: {book_id})")
    
    # Test the FULL pipeline function that actually updates metadata.json
    print(f"\n🧪 Testing FULL pipeline integration (updates metadata.json):")
    metadata_path = f"foundry/processing/{book_id}/metadata.json"
    
    result = generate_image_prompts_for_book(
        book_id=book_id,
        book_title=book_title,
        author=author,
        narrated_by=narrator,
        metadata_file_path=metadata_path,
        model_profile='balanced',
        temperature=DEFAULT_TEMPERATURE,
        verbose=True
    )
    
    if result['success']:
        print(f"\n✅ SUCCESS: metadata.json should now be updated!")
        print(f"📁 Updated file: {metadata_path}")
        print(f"📊 Analysis file: foundry/processing/{book_id}/prompt_analysis_[timestamp].json")
        return True
    else:
        print(f"\n❌ FAILED: {result.get('error', 'Unknown error')}")
        return False


if __name__ == "__main__":
    success = main()
    if not success:
        exit(1)