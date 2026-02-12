---
config:
  layout: dagre
---
flowchart TB
 subgraph subGraph0["PHASE 1: Chat Completion & Embedding Generation"]
        B{"Previous Chat Exists?"}
        A["User Starts NEW Chat"]
        C["Get Previous Chat Messages"]
        Z["Skip to Phase 2"]
        D["Generate Summary via GPT-4o-mini"]
        E["Summary Created:<br>User learned about Python decorators..."]
        F{"Embedding Exists?"}
        G["Generate Embedding via<br>text-embedding-3-small API"]
        H["Skip Embedding Generation"]
        I["Create 1536-dimensional Vector:<br>(0.123, -0.456, 0.789, ...)"]
        J["Store in embeddings Table:<br>- summary_id<br>- user_id<br>- chat_id<br>- summary_text<br>- embedding_vector<br>- metadata"]
        K["Extract Facts from Summary:<br>User knows Python decorators"]
        L["Update user_profile Table:<br>- important_facts<br>- preferences<br>- topics_of_interest"]
        M["✓ Chat Embedding Stored"]
  end
 subgraph subGraph1["PHASE 2: User Query & Response Generation"]
        O["get_or_create_chat"]
        N["User Sends Message:<br>How do I create a Python decorator?"]
        P["Get Last 5 Message Pairs<br>from Current Chat<br>Sliding Window"]
        Q["generate_response Called"]
        R["Step A: Get User Profile"]
        S["Retrieve Compressed Facts:<br>Knows Python decorators,<br>Interested in Python programming"]
        T["Step B: Semantic Search"]
        U["Generate Query Embedding<br>for User Message"]
        V["Search ALL Previous Chat<br>Embeddings via Vector DB"]
        W{"Exclude Current Chat"}
        X["Calculate Cosine Similarity<br>with ALL Embeddings"]
        Y["Filter by Threshold > 0.7"]
        AA["Retrieve Top 3-5 Most Similar<br>Chat Summaries"]
        AB["Chat 1: similarity 0.95<br>Chat 15: similarity 0.91<br>Chat 32: similarity 0.89"]
        AC["Step C: Recent Messages"]
        AD["Get Last 5 Message Pairs<br>from CURRENT Chat"]
        AE["Step D: Current Message"]
        AF["Context Assembly"]
        AG{"Assemble Final Context"}
        AH["1. User Profile<br>Compressed Facts"]
        AI["2. Historical Contexts<br>Top 3-5 Relevant Summaries"]
        AJ["3. Recent Messages<br>Last 5 Pairs"]
        AK["4. Current Message<br>User Query"]
        AL["Send to LLM<br>gpt-4o-mini"]
        AM["Generate AI Response"]
        AN["Save Message Pair<br>to Database"]
        AO["✓ Response Delivered"]
  end
    A --> B
    B -- Yes --> C
    B -- No --> Z
    C --> D
    D --> E
    E --> F
    F -- No --> G
    F -- Yes --> H
    G --> I
    I --> J
    J --> K
    K --> L
    L --> M
    N --> O
    O --> P
    P --> Q
    Q --> R & T & AC & AE
    R --> S
    T --> U
    U --> V
    V --> W
    W --> X
    X --> Y
    Y --> AA
    AA --> AB
    AC --> AD
    S --> AF
    AB --> AF
    AD --> AF
    AE --> AF
    AF --> AG
    AG --> AH & AI & AJ & AK
    AH --> AL
    AI --> AL
    AJ --> AL
    AK --> AL
    AL --> AM
    AM --> AN
    AN --> AO
    M -. Embeddings Ready .-> N

    style A fill:#e1f5ff
    style M fill:#c8e6c9
    style N fill:#e1f5ff
    style AF fill:#fff9c4
    style AL fill:#ffccbc
    style AO fill:#c8e6c9