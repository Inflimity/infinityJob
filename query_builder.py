from core.heuristic_filters import CRYPTO_ENTITIES, CRYPTO_ACTIONS, PROBLEM_WORDS

def build_twitter_queries():
    targets = CRYPTO_ENTITIES + CRYPTO_ACTIONS
    problems = PROBLEM_WORDS
    
    # Twitter search max length is ~500 chars. 
    # Let's chunk them into groups of ~10 words.
    target_chunks = [targets[i:i+8] for i in range(0, len(targets), 8)]
    problem_chunks = [problems[i:i+8] for i in range(0, len(problems), 8)]
    
    queries = []
    for t_chunk in target_chunks:
        for p_chunk in problem_chunks:
            t_str = " OR ".join(f'"{x}"' if ' ' in x else x for x in t_chunk)
            p_str = " OR ".join(f'"{x}"' if ' ' in x else x for x in p_chunk)
            q = f"({t_str}) ({p_str})"
            queries.append(q)
            
    return queries

queries = build_twitter_queries()
print(f"Total queries generated: {len(queries)}")
print(queries[0])
print(len(queries[0]))
