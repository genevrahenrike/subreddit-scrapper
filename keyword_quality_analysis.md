# Keyword Extraction Quality Analysis Report

## Executive Summary

I analyzed the keyword extraction results from your complete 100k subreddit dataset across both v22 (baseline) and v22_embed (with embedding reranking) versions. Here's my assessment:

## Overall Quality Assessment: **B+ to A-**

### Strengths ✅

1. **Excellent Phrase Composition**: The system successfully creates contextual, branded phrases:
   - `r/gaming`: "r/gaming hollow knight silksong", "gaming hollow knight silksong"
   - `r/CX5Mods`: "CX5Mods spark plugs", "CX5Mods mazda cx5 turbo"
   - `r/personalfinance`: "Personal Finance credit card", "personalfinance savings account"

2. **Strong Theme Alignment**: Keywords match subreddit purposes very well:
   - `r/AskReddit`: Captures question patterns ("Ask Reddit... job pays", "thought provoking questions")
   - `r/cooking`: Food-focused terms dominate ("recipe", "chicken", "ingredients")
   - `r/programming`: Technical terms surface ("programming language", "rust", "mongodb")

3. **Good Source Diversity**: Balanced integration of name, description, and posts sources
   - Name-derived terms provide brand identity
   - Description terms capture official purpose
   - Posts terms reflect actual community activity

4. **High Composition Rate**: 70-80% of top-10 keywords are composed phrases in most subreddits

### Issues Found ⚠️

1. **Spam/Ad Contamination**: Some posts appear to be promotional content that pollutes keywords:
   - `r/worldnews`: "Marvel Rivals Season 3" (gaming ad in news subreddit)
   - `r/explainlikeimfive`: "SkinnyRx Tirzepatide" (pharmaceutical ad)
   - Various healthcare/product ads scattered across subreddits

2. **Language Mixing**: Non-English content creates noisy keywords:
   - `r/CX5Mods`: Spanish boxing terms ("dos campeones un título sé testigo")

3. **Over-Aggressive Composition**: Some composed phrases feel mechanical:
   - `r/funny`: "funny happens die black phone" (fragments from unrelated posts)
   - Multiple variations of same concept cluttering top results

4. **URL/Technical Artifacts**: Raw URLs and technical terms surface:
   - `r/gaming`: "https store steampowered", "nintendo com store"

## Comparison: V22 vs V22_Embed

The embedding reranking shows **modest improvements**:

### Embed Version Benefits:
- **Slightly better thematic coherence** (description terms often rank higher)
- **Reduced noise** in some cases (see r/funny, r/gaming scores)
- **Better semantic grouping** of related concepts

### Minimal Difference:
- Core quality issues remain the same
- Composition patterns are identical
- Both versions suffer from the same contamination sources

## Quality by Subreddit Category

### Excellent Quality (A grade):
- **Cooking**: Clean, food-focused vocabulary
- **Programming**: Technical terms well-extracted
- **PersonalFinance**: Financial concepts clearly captured

### Good Quality (B+ grade):
- **AskReddit**: Question patterns detected well
- **Gaming**: Game-specific terms dominate despite some URL noise
- **ExplainLikeImFive**: Educational focus clear with some ad contamination

### Problematic (B- grade):
- **WorldNews**: Significant ad contamination affecting theme
- **Funny**: Generic humor mixed with irrelevant fragments

## Recommendations for Improvement

### High Priority:
1. **Ad Filtering**: Implement promotional content detection to filter spam posts
2. **Language Detection**: Filter non-English content or process separately
3. **URL Cleanup**: Strip technical artifacts (URLs, domains) from keyword candidates

### Medium Priority:
4. **Composition Refinement**: Reduce over-composition of fragmented phrases
5. **Deduplication**: Merge very similar composed variants
6. **Quality Scoring**: Boost coherent phrases over fragmented ones

### Low Priority:
7. **Temporal Filtering**: Consider post age/engagement in source selection
8. **Category-Specific Tuning**: Different parameters for different subreddit types

## Technical Performance

- **Processing Coverage**: 404 pages in v22, 299 in v22_embed (74% completion rate for embed)
- **Composition Success**: 5-8 out of 10 top keywords are composed phrases
- **Score Distribution**: Wide range with clear quality tiers (good for filtering)

## Conclusion

The keyword extraction pipeline is performing well for most subreddits, successfully capturing thematic content and creating branded, contextual phrases. The main quality issues stem from **input data contamination** (ads, spam, non-English content) rather than algorithmic problems. 

**Recommendation**: Focus next iteration on **input filtering** rather than algorithm changes. The core extraction logic is sound.
