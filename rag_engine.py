"""
Core RAG / LLM engine — ported from the original Mino-chat.py (Streamlit).

All Streamlit-specific code (st.session_state, st.spinner, st.rerun, ...) has
been removed. This module is framework-agnostic: it exposes plain Python
functions/classes that the Flask app (chat_api.py) calls directly.

Per-conversation state (LangChain message history) lives in an in-memory
dict, keyed by a "runtime session id" that Flask hands out via a signed
cookie. This mirrors the original `store = {}` used by
RunnableWithMessageHistory in the Streamlit version.
"""
import os
import json
import glob
import hashlib


import fitz  # PyMuPDF

from langchain_community.document_loaders import PyMuPDFLoader
from langchain_community.vectorstores import FAISS
from langchain_community.chat_message_histories import ChatMessageHistory
from langchain_community.tools.tavily_search import TavilySearchResults

from langchain_openai import AzureChatOpenAI, AzureOpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnableWithMessageHistory, RunnablePassthrough
from langchain_core.output_parsers import JsonOutputParser
from langchain.chains.combine_documents import create_stuff_documents_chain


SHOULD_NOT_ANSWER = """
- Finance, investment, banking, loans, mortgages, taxes, insurance, pensions, stock markets, trading, cryptocurrency, or any other financial topics.
- Medical diagnosis, treatment recommendations, prescription advice, or emergency health guidance.
- Legal advice, immigration case strategy, visa decisions, or interpretation of laws.
- Political campaigning, political persuasion, election recommendations, or partisan advice.
- Instructions for illegal activities, fraud, hacking, scams, or evading law enforcement.
- Instructions for creating or using weapons, explosives, or other dangerous materials.
- Harmful, hateful, discriminatory, extremist, or violent content.
- Sexual or explicit content.
- Personal data requests, identity theft, surveillance, or privacy-invasive activities.
- Professional advice that should come from licensed experts (financial, legal, medical, or mental health professionals).
"""

SHOULD_NOT_ANSWER_SUMMARY = """
- Finance or investment.
- Medical, legal, immigration, or professional advice.
- Politics or election persuasion.
- Illegal, harmful, dangerous, fraudulent, or hacking activities.
- Weapons or explosives.
- Hate, discrimination, violence, or explicit sexual content.
- Personal data, privacy invasion, or identity theft.
"""

BASE_SECTION_DESCRIPTIONS = {
    "CIWA": "Chinese in Wales Association — activities, events, community support, membership, cultural programmes.",
    "RCC": "Race Council Cymru - activities, events, community support, race equality policy, advocacy, community engagement, Welsh race relations.",
    "GENERAL": "General anti-racism information, Online Safety Act, hate crime legislation, anti-racism frameworks, Equality data, statistics, demographics, anti-racism metrics, diversity reports.",
    "DATA": "Glossary of data terms and definitions, Social media Platform terms and conditions, political and cultural corpus",
    "PERSONA": "Information about the community personas, its purpose, capabilities, and limitations. Use it when different perspectives, communities are needed for answering questions.",
}

OUTPUT_RESPONSE_INSTRUCTIONS = """
    "Tone: Warm, calm and respectful. Avoid being overly casual or humorous."
    "Answer conversationally, politely, and concisely. "
    "Never present biased, offensive, or harmful content."
    "Do not fabricate information. If you don't know the answer, say so politely."

"""

# class HateSpeechICL:
#     """
#     Hate Speech ICL Classifier — uses labeled vignettes (race/ethnicity,
#     religion/belief, national origin, ...) as retrieval-based few-shot
#     exemplars for LLM hate speech detection (explicit + implicit).

#     Heavy dependencies (pandas, numpy, sentence-transformers, scikit-learn)
#     are imported lazily inside __init__ so that a missing dependency only
#     disables this one "Analyzer" tool rather than the whole RAG engine.
#     """

#     def __init__(self, csv_paths, embed_model="all-MiniLM-L6-v2"):
#         import pandas as pd
#         from sentence_transformers import SentenceTransformer

#         dfs = [pd.read_csv(p) for p in csv_paths]
#         self.df = pd.concat(dfs, ignore_index=True).reset_index(drop=True)
#         self.embedder = SentenceTransformer(embed_model)
#         self.embeddings = self.embedder.encode(
#             self.df["text"].tolist(), normalize_embeddings=True
#         )

#     def retrieve_shots(self, query, k=6, force_diversity=True):
#         """Retrieve top-k semantically similar vignettes; guarantee
#         at least one explicit and one implicit example are included."""
#         import numpy as np
#         from sklearn.metrics.pairwise import cosine_similarity

#         q_emb = self.embedder.encode([query], normalize_embeddings=True)
#         sims = cosine_similarity(q_emb, self.embeddings)[0]
#         ranked_idx = np.argsort(-sims)

#         shots = []
#         seen_types = set()
#         for idx in ranked_idx:
#             row = self.df.iloc[idx]
#             if len(shots) >= k:
#                 break
#             if force_diversity and len(shots) >= k - 2:
#                 if row["implicit_explicit"] not in seen_types and len(seen_types) < 2:
#                     shots.append(row)
#                     seen_types.add(row["implicit_explicit"])
#                 continue
#             shots.append(row)
#             seen_types.add(row["implicit_explicit"])

#         if len(shots) < k:
#             existing_texts = [s["text"] for s in shots]
#             for idx in ranked_idx:
#                 row = self.df.iloc[idx]
#                 if row["text"] not in existing_texts:
#                     shots.append(row)
#                 if len(shots) >= k:
#                     break
#         return shots

#     def build_prompt(self, query_text, k=6):
#         shots = self.retrieve_shots(query_text, k=k)

#         instructions = (
#             "You are a hate speech annotation expert. Classify the INPUT "
#             "text using the same schema as the EXAMPLES below.\n"
#             "Fields to output (JSON):\n"
#             "- is_hate_speech: true/false\n"
#             "- severity_tier: one of [none, low, moderate, high, extreme]\n"
#             "- implicit_explicit: one of [explicit, implicit, none]\n"
#             "- strategy: e.g. dehumanisation, direct_threat, insult_based, "
#             "slur_heavy, coded_implicit, general_toxic, low_signal, none\n"
#             "- target_group: group targeted, or 'none'\n"
#             "- rationale: one sentence explaining the cue(s) used, "
#             "especially if the hate is implicit/coded rather than a slur.\n\n"
#             "Pay special attention to IMPLICIT hate: coded language, "
#             "dehumanising comparisons, dog-whistles, and stereotypes without "
#             "explicit slurs are still hate speech.\n\nEXAMPLES:\n"
#         )

#         example_block = ""
#         for s in shots:
#             example_block += (
#                 f"Text: {s['text']}\n"
#                 f"Label: {{\"is_hate_speech\": true, "
#                 f"\"severity_tier\": \"{s['severity_tier']}\", "
#                 f"\"implicit_explicit\": \"{s['implicit_explicit']}\", "
#                 f"\"strategy\": \"{s['strategy']}\", "
#                 f"\"target_group\": \"{s['target_group']}\"}}\n\n"
#             )

#         return instructions + example_block + f"Now classify this INPUT:\nText: {query_text}\nLabel:"

class HateSpeechICL:
    """
    Hate Speech ICL Classifier — uses labeled vignettes (race/ethnicity,
    religion/belief, national origin, ...) as retrieval-based few-shot
    exemplars for LLM hate speech detection (explicit + implicit).

    Heavy dependencies (pandas, numpy, langchain_openai, scikit-learn)
    are imported lazily inside __init__ so that a missing dependency only
    disables this one "Analyzer" tool rather than the whole RAG engine.
    """

    def __init__(self, csv_paths, app_config, embed_model=None):
        import pandas as pd
        import numpy as np
        

        dfs = [pd.read_csv(p) for p in csv_paths]
        self.df = pd.concat(dfs, ignore_index=True).reset_index(drop=True)

        # Azure OpenAI embedding client
        self.embedder = AzureOpenAIEmbeddings(
            azure_endpoint=app_config["AZURE_OPENAI_ENDPOINT"],
            azure_deployment=app_config["AZURE_OPENAI_EMBEDDING_DEPLOYMENT"],
            api_version=app_config["AZURE_OPENAI_API_VERSION"],
            api_key=app_config["AZURE_OPENAI_API_KEY"],
        )

        raw_embeddings = self.embedder.embed_documents(self.df["text"].tolist())
        self.embeddings = self._normalize(np.array(raw_embeddings, dtype="float32"))

    @staticmethod
    def _normalize(mat):
        import numpy as np
        norms = np.linalg.norm(mat, axis=1, keepdims=True)
        norms[norms == 0] = 1e-10
        return mat / norms

    def retrieve_shots(self, query, k=6, force_diversity=True):
        """Retrieve top-k semantically similar vignettes; guarantee
        at least one explicit and one implicit example are included."""
        import numpy as np
        from sklearn.metrics.pairwise import cosine_similarity

        q_emb = np.array(self.embedder.embed_query(query), dtype="float32").reshape(1, -1)
        q_emb = self._normalize(q_emb)

        sims = cosine_similarity(q_emb, self.embeddings)[0]
        ranked_idx = np.argsort(-sims)

        shots = []
        seen_types = set()
        for idx in ranked_idx:
            row = self.df.iloc[idx]
            if len(shots) >= k:
                break
            if force_diversity and len(shots) >= k - 2:
                if row["implicit_explicit"] not in seen_types and len(seen_types) < 2:
                    shots.append(row)
                    seen_types.add(row["implicit_explicit"])
                continue
            shots.append(row)
            seen_types.add(row["implicit_explicit"])

        if len(shots) < k:
            existing_texts = [s["text"] for s in shots]
            for idx in ranked_idx:
                row = self.df.iloc[idx]
                if row["text"] not in existing_texts:
                    shots.append(row)
                if len(shots) >= k:
                    break
        return shots

    def build_prompt(self, query_text, k=6):
        shots = self.retrieve_shots(query_text, k=k)

        instructions = (
            "You are a hate speech annotation expert. Classify the INPUT "
            "text using the same schema as the EXAMPLES below.\n"
            "Fields to output (JSON):\n"
            "- is_hate_speech: true/false\n"
            "- severity_tier: one of [none, low, moderate, high, extreme]\n"
            "- implicit_explicit: one of [explicit, implicit, none]\n"
            "- strategy: e.g. dehumanisation, direct_threat, insult_based, "
            "slur_heavy, coded_implicit, general_toxic, low_signal, none\n"
            "- target_group: group targeted, or 'none'\n"
            "- rationale: one sentence explaining the cue(s) used, "
            "especially if the hate is implicit/coded rather than a slur.\n\n"
            "Pay special attention to IMPLICIT hate: coded language, "
            "dehumanising comparisons, dog-whistles, and stereotypes without "
            "explicit slurs are still hate speech.\n\nEXAMPLES:\n"
        )

        example_block = ""
        for s in shots:
            example_block += (
                f"Text: {s['text']}\n"
                f"Label: {{\"is_hate_speech\": true, "
                f"\"severity_tier\": \"{s['severity_tier']}\", "
                f"\"implicit_explicit\": \"{s['implicit_explicit']}\", "
                f"\"strategy\": \"{s['strategy']}\", "
                f"\"target_group\": \"{s['target_group']}\"}}\n\n"
            )

        return instructions + example_block + f"Now classify this INPUT:\nText: {query_text}\nLabel:"
    
class RagEngine:
    """Wraps LLM/embeddings, section vectorstores, and the routing chain.
    One instance is created at app startup and stored on `app.rag_engine`.
    """

    def __init__(self, app_config):
        self.cfg = app_config
        self.data_path = app_config["DATA_PATH"]
        self.vectorstore_root = app_config["VECTORSTORE_ROOT"]
        self.upload_section = app_config["UPLOAD_SECTION"]
        self.max_history_msgs = app_config["MAX_HISTORY_MSGS"]

        self.chat_llm = AzureChatOpenAI(
            azure_endpoint=app_config["AZURE_OPENAI_ENDPOINT"],
            azure_deployment=app_config["AZURE_OPENAI_DEPLOYMENT"],
            api_version=app_config["AZURE_OPENAI_API_VERSION"],
            api_key=app_config["AZURE_OPENAI_API_KEY"],
            temperature=0.6,
            top_p=0.95,
            max_tokens=800,
        )

        self.embedding_llm = AzureOpenAIEmbeddings(
            azure_endpoint=app_config["AZURE_OPENAI_ENDPOINT"],
            azure_deployment=app_config["AZURE_OPENAI_EMBEDDING_DEPLOYMENT"],
            api_version=app_config["AZURE_OPENAI_API_VERSION"],
            api_key=app_config["AZURE_OPENAI_API_KEY"],
        )

        self.tavily_api_key = app_config.get("TAVILY_API_KEY")
        if self.tavily_api_key:
            os.environ.setdefault("TAVILY_API_KEY", self.tavily_api_key)
        self.hate_speech_icl = self._load_hate_speech_icl(app_config)

        # message-history store: runtime_session_id -> ChatMessageHistory
        self._history_store = {}

        # section_name -> FAISS  (base sections, shared across all users)
        self.section_stores = {}
        # per runtime_session_id -> FAISS (user-attached PDFs, private)
        self._upload_stores = {}

        # conversation chain, rebuilt whenever section_stores changes
        self.conversation_chain = None
        self.routing_info = {"sections": [], "reason": "", "needs_vectorstore": None}

        self.load_base_sections(force_rebuild=False)

    # ── PDF ingestion ────────────────────────────────────────────────────
    def _get_pdf_docs(self, pdf_dir: str, section_name: str) -> list:
        if not os.path.isdir(pdf_dir):
            return []
        pdf_paths = [
            os.path.join(pdf_dir, f) for f in os.listdir(pdf_dir) if f.lower().endswith(".pdf")
        ]
        all_docs = []
        for pdf_path in pdf_paths:
            meta = fitz.open(pdf_path).metadata
            title = (meta.get("title") or "").strip() or os.path.splitext(os.path.basename(pdf_path))[0]
            docs = PyMuPDFLoader(pdf_path).load()
            for doc in docs:
                doc.metadata["doc_title"] = title
                doc.metadata["section"] = section_name
                doc.metadata["doc_year"] = "2026"
                doc.metadata["page_hash"] = hashlib.md5(doc.page_content.encode()).hexdigest()
            all_docs.extend(docs)
        return all_docs

    @staticmethod
    def _chunk_docs(docs: list) -> list:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=512, chunk_overlap=64,
            separators=["\n\n", "\n", ". ", " ", ""], add_start_index=True,
        )
        chunks = splitter.split_documents(docs)
        for i, chunk in enumerate(chunks):
            page = chunk.metadata.get("page")
            chunk.metadata["chunk_id"] = i
            chunk.metadata["chunk_source"] = (
                f"{chunk.metadata.get('source', 'unknown')} | "
                f"Page {page + 1 if page is not None else '?'} | "
                f"Char offset: {chunk.metadata.get('start_index', '?')}"
            )
        return chunks

    def _section_store_path(self, section_name: str) -> str:
        return os.path.join(self.vectorstore_root, section_name)

    def _vectorstore_exists(self, section_name: str) -> bool:
        return os.path.exists(os.path.join(self._section_store_path(section_name), "index.faiss"))

    def _load_vectorstore(self, section_name: str) -> FAISS:
        return FAISS.load_local(
            self._section_store_path(section_name), self.embedding_llm,
            allow_dangerous_deserialization=True,
        )

    def _build_vectorstore(self, chunks: list, section_name: str) -> FAISS:
        store_path = self._section_store_path(section_name)
        vectorstore = FAISS.from_documents(documents=chunks, embedding=self.embedding_llm)
        os.makedirs(store_path, exist_ok=True)
        vectorstore.save_local(store_path)
        return vectorstore

    def load_base_sections(self, force_rebuild: bool = False) -> dict:
        """(Re)builds/loads every section folder under DATA_PATH and refreshes
        the conversation chain. Returns the resulting section_stores dict."""
        section_stores = {}
        if os.path.isdir(self.data_path):
            sections = [
                d for d in os.listdir(self.data_path)
                if os.path.isdir(os.path.join(self.data_path, d))
            ]
            for section in sections:
                section_pdf_dir = os.path.join(self.data_path, section)
                if not force_rebuild and self._vectorstore_exists(section):
                    store = self._load_vectorstore(section)
                else:
                    docs = self._get_pdf_docs(section_pdf_dir, section_name=section)
                    if not docs:
                        continue
                    chunks = self._chunk_docs(docs)
                    store = self._build_vectorstore(chunks, section_name=section)
                section_stores[section] = store

        self.section_stores = section_stores
        self._rebuild_chain()
        return section_stores

    def build_upload_store_for_session(self, runtime_session_id: str, file_paths: list):
        """Indexes user-attached PDFs into a private per-session FAISS store."""
        all_docs = []
        for path in file_paths:
            meta = fitz.open(path).metadata
            title = (meta.get("title") or "").strip() or os.path.splitext(os.path.basename(path))[0]
            docs = PyMuPDFLoader(path).load()
            for doc in docs:
                doc.metadata["doc_title"] = title
                doc.metadata["section"] = self.upload_section
                doc.metadata["doc_year"] = "2026"
                doc.metadata["page_hash"] = hashlib.md5(doc.page_content.encode()).hexdigest()
            all_docs.extend(docs)

        if not all_docs:
            return None

        chunks = self._chunk_docs(all_docs)
        existing = self._upload_stores.get(runtime_session_id)
        if existing is not None:
            existing.add_documents(chunks)
            store = existing
        else:
            store = FAISS.from_documents(documents=chunks, embedding=self.embedding_llm)
        self._upload_stores[runtime_session_id] = store
        return store

    def clear_upload_store(self, runtime_session_id: str) -> None:
        self._upload_stores.pop(runtime_session_id, None)

    def has_knowledge(self, runtime_session_id: str) -> bool:
        return bool(self.section_stores) or runtime_session_id in self._upload_stores
    
    def _load_hate_speech_icl(self, app_config):
        """Lazily builds the HateSpeechICL classifier from any CSVs found in
        HATE_SPEECH_INDEX_DIR. Returns None (feature disabled) if no CSVs
        are present or the optional dependencies aren't installed —
        callers must handle that gracefully rather than assume it exists."""
        index_dir = app_config.get("HATE_SPEECH_INDEX_DIR")
        if not index_dir or not os.path.isdir(index_dir):
            return None
        csv_paths = sorted(glob.glob(os.path.join(index_dir, "*.csv")))
        if not csv_paths:
            return None
        try:
            return HateSpeechICL(csv_paths,app_config)
        except Exception as exc:  # missing pandas/sentence-transformers/sklearn, bad CSV, etc.
            print(f"[rag_engine] Hate speech analyzer disabled: {exc}")
            return None
        
    def web_search(self, query: str, k: int = 5) -> dict:
        """Searches the web and answers using the chat LLM, grounded only in
        the search results. Returns {"answer": str, "references": [url, ...]}."""
        if not (self.tavily_api_key or os.environ.get("TAVILY_API_KEY")):
            return {
                "answer": "Web search isn't configured on this server (missing TAVILY_API_KEY).",
                "references": [],
            }

        try:
            search = TavilySearchResults(max_results=k)
            results = search.invoke(query)
        except Exception as exc:
            return {"answer": f"Web search failed: {exc}", "references": []}

        if not results:
            return {"answer": "No web results were found for this question.", "references": []}

        context = ""
        references = []
        for i, r in enumerate(results, 1):
            context += (
                f"\nResult {i}\nTitle: {r.get('title', '')}\n"
                f"Content: {r.get('content', '')}\nURL: {r.get('url', '')}\n"
            )
            if r.get("url"):
                references.append(r["url"])

        prompt = (
            "You are a helpful assistant.\n\n"
            "Answer the following question using ONLY the web search results.\n\n"
            f"Question:\n{query}\n\nWeb Search Results:\n{context}\n\n"
            "Provide a concise but informative answer."
        )
        response = self.chat_llm.invoke(prompt)
        answer = response.content if hasattr(response, "content") else str(response)
        return {"answer": answer, "references": references}

    # ── Tool: hate speech analyzer ──────────────────────────────────────
    def analyze_hate_speech(self, text: str, k: int = 6) -> dict:
        """Classifies text for explicit/implicit hate speech using the ICL
        classifier. Returns a dict with is_hate_speech/severity_tier/etc.,
        or {"error": ...} if the analyzer isn't available / parsing failed."""
        if not self.hate_speech_icl:
            return {"error": "The hate speech analyzer isn't available on this server (missing index files or dependencies)."}

        prompt = self.hate_speech_icl.build_prompt(text, k=k)
        # print(f"[rag_engine] Hate speech prompt:\n{prompt}\n")
        raw_response = self.chat_llm.invoke(prompt)
        raw_text = raw_response.content if hasattr(raw_response, "content") else str(raw_response)
        try:
            start = raw_text.find("{")
            end = raw_text.rfind("}") + 1
            return json.loads(raw_text[start:end])
        except Exception:
            return {"error": "parse_failed", "raw": raw_text}

    # ── Chat history store + summarization ──────────────────────────────
    def _summarize_if_needed(self, history: ChatMessageHistory):
        if len(history.messages) <= self.max_history_msgs:
            return
        summarization_prompt = ChatPromptTemplate.from_messages([
            MessagesPlaceholder(variable_name="chat_history"),
            ("user", "Distill the above chat messages into a single concise summary. "
                     "Preserve key entities, decisions, and unresolved questions."),
        ])
        summarization_chain = summarization_prompt | self.chat_llm
        summary_message = summarization_chain.invoke({"chat_history": history.messages})
        history.clear()
        history.add_ai_message(f"Summary of earlier conversation: {summary_message.content}")

    def get_session_history(self, runtime_session_id: str) -> ChatMessageHistory:
        if runtime_session_id not in self._history_store:
            self._history_store[runtime_session_id] = ChatMessageHistory()
        history = self._history_store[runtime_session_id]
        self._summarize_if_needed(history)
        return history

    def reset_session_history(self, runtime_session_id: str) -> None:
        self._history_store.pop(runtime_session_id, None)

    def seed_session_history(self, runtime_session_id: str, messages: list) -> None:
        """Rehydrate LangChain memory from DB-loaded messages, e.g. when a
        user reopens a previously saved chat."""
        history = ChatMessageHistory()
        for m in messages:
            if m["role"] == "user":
                history.add_user_message(m["content"])
            else:
                history.add_ai_message(m["content"])
        self._history_store[runtime_session_id] = history

    # ── Conversation chain: clarify -> route -> retrieve -> answer ──────
    def _rebuild_chain(self):
        section_stores = self.section_stores
        section_descriptions = {
            name: BASE_SECTION_DESCRIPTIONS.get(name, f"Documents from the '{name}' folder.")
            for name in section_stores
        }
        section_list = "\n".join(f"- {k}: {v}" for k, v in section_descriptions.items())

        routing_info = self.routing_info

        clarification_prompt = ChatPromptTemplate.from_messages([
            ("system",
             "You are 'community chat', a helpful assistant specialising in community organisations in Wales specially for CIWA : Chinese in Wales Association and RCC : Race council Cymru. Analyze the chat history and the latest user question to determine if the question is clear enough to search a knowledge base.\n\n"
             "If the question is about application services, anything about the personas, or any of the knowledge base sections, set needs_clarification to false and provide a rewritten question that is optimized for search.\n\n"
             f"If the query is about the {SHOULD_NOT_ANSWER_SUMMARY} topics, set needs_clarification to false and provide a rewritten question that politely declines to answer.\n\n"
             "Respond strictly with this JSON structure:\n"
             "{{\n"
             '  "needs_clarification": true|false,\n'
             '  "rewritten_question": "Standalone, decontextualized query optimized for search. Search always performed on English. Empty string if needs_clarification is true.",\n'
             '  "clarification_message": "Polite follow-up question if needs_clarification is true. Empty string if false."\n'
             "}}\n\n"
             "- Set needs_clarification to true only if the query is structurally ambiguous or missing key entities to answer Specially about organization information and time related facts.\n"
             "- If you have already asked for clarification in the chat history, do not ask again; instead, set needs_clarification to false and provide a rewritten question.\n"
             "- Never include markdown, explanation, or text outside the JSON."),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{input}\n\nResponse JSON:"),
        ])

        router_prompt = ChatPromptTemplate.from_messages([
            ("system",
             f"You are a query routing agent. Given a user question, decide:\n"
             f"1. Whether a vector database search is needed at all.\n"
             f"2. Which of the following knowledge bases to search (can be multiple):\n\n"
             f"3. If multiple perspectives or personas are needed to answer the question, include the 'PERSONA' section.\n\n"
             f"{section_list}\n\n"
             "Respond strictly with this JSON structure:\n"
             "{{\n"
             '  "needs_vectorstore": true|false,\n'
             '  "sections": ["SECTION_NAME_1", "SECTION_NAME_2"],\n'
             '  "reason": "One sentence explaining which stores were selected and why."\n'
             "}}\n\n"
             "Rules:\n"
             "- If the question is conversational (greetings, thanks, general chit-chat) set needs_vectorstore to false and sections to [].\n"
             "- If the question relates to multiple sections, list all relevant ones.\n"
             "- Only use section names from the provided list exactly as written.\n"
             "- Never include markdown or text outside the JSON."),
            ("human", "{input}\n\nResponse JSON:"),
        ])

        try:
            bound_llm = self.chat_llm.bind(response_format={"type": "json_object"})
        except (AttributeError, NotImplementedError):
            bound_llm = self.chat_llm

        clarification_analyzer = clarification_prompt | bound_llm | JsonOutputParser()
        store_router = router_prompt | bound_llm | JsonOutputParser()

        qa_prompt = ChatPromptTemplate.from_messages([
            ("system",
             "You are 'community chat', a helpful assistant specialising in community organisations in Wales. "
             "You must always maintain accuracy, relevance, and a polite tone. Always reply in the same language where the question was asked.\n"
             f"Do not answer any thing about {SHOULD_NOT_ANSWER}. If the question is about one of these topics, politely decline to answer.\n\n"
             f"Follow these rules when answering:\n"
             f"{OUTPUT_RESPONSE_INSTRUCTIONS}"
             "Sources searched: {sources_searched}\n\n"
             "Context:\n{context}"),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{input}"),
        ])
        question_answer_chain = create_stuff_documents_chain(self.chat_llm, qa_prompt)

        direct_prompt = ChatPromptTemplate.from_messages([
            ("system",
             "You are 'community chat', a helpful assistant specialising in community organisations in Wales. "
             "You must always maintain accuracy, relevance, and a polite tone. Always reply in the same language where the question was asked."
             f"Do not answer any thing about {SHOULD_NOT_ANSWER}. If the question is about one of these topics, politely decline to answer.\n\n"
             f"Follow these rules when answering:\n"
             f"{OUTPUT_RESPONSE_INSTRUCTIONS}"
             "Answer conversationally without needing to reference documents."),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{input}"),
        ])
        direct_chain = direct_prompt | self.chat_llm

        def route_and_retrieve(inputs):
            chat_history = inputs.get("chat_history", [])
            user_input = inputs["input"]
            runtime_session_id = inputs.get("runtime_session_id")

            explicit_sections = [s for s in (inputs.get("forced_sections") or []) if s]

            routing_info.update({"sections": [], "reason": "", "needs_vectorstore": None})

            # merge base sections with this session's private upload store
            active_stores = dict(section_stores)
            upload_store = self._upload_stores.get(runtime_session_id)
            if upload_store is not None:
                active_stores[self.upload_section] = upload_store

            # Skip the clarification agent entirely once a PDF has been attached.
            if upload_store is not None or explicit_sections:
                optimized_query = user_input
                routing_info["reason"] = "Clarification skipped: PDF attached this session."
            else:
                clarification = clarification_analyzer.invoke({
                    "chat_history": chat_history, "input": user_input,
                })
                if clarification.get("needs_clarification", False):
                    routing_info["reason"] = "Clarification requested before searching."
                    return clarification.get("clarification_message", "Could you please clarify your question?")

                optimized_query = clarification.get("rewritten_question") or user_input

            if not active_stores:
                response = direct_chain.invoke({"chat_history": chat_history, "input": user_input})
                routing_info["needs_vectorstore"] = False
                routing_info["reason"] = "No knowledge base is currently loaded."
                return response.content if hasattr(response, "content") else str(response)

            local_descriptions = dict(section_descriptions)
            if upload_store is not None:
                local_descriptions[self.upload_section] = (
                    "Documents the user attached in this chat session. If asked about these "
                    "documents, only use the content of the attached PDFs."
                )
            local_section_list = "\n".join(f"- {k}: {v}" for k, v in local_descriptions.items())
            local_router_prompt = ChatPromptTemplate.from_messages([
                ("system",
                 "You are a query routing agent. Given a user question, decide:\n"
                 "1. Whether a vector database search is needed at all.\n"
                 f"2. Which of the following knowledge bases to search (can be multiple):\n\n{local_section_list}\n\n"
                 "Respond strictly with this JSON structure:\n"
                 "{{\n  \"needs_vectorstore\": true|false,\n  \"sections\": [\"SECTION_NAME_1\"],\n  \"reason\": \"...\"\n}}\n\n"
                 "  Rules:\n- If conversational, set needs_vectorstore false and sections [].\n"
                 "- Only use section names from the list exactly as written.\n"
                 "- Never include markdown or text outside the JSON."),
                ("human", "{input}\n\nResponse JSON:"),
            ])
            local_router = local_router_prompt | bound_llm | JsonOutputParser()
            routing = local_router.invoke({"input": optimized_query}) if upload_store is not None else store_router.invoke({"input": optimized_query})

            # ── Force-include the attached PDF's store ──────────────────
           
            if upload_store is not None or explicit_sections:
                routing["needs_vectorstore"] = True
                forced_sections = routing.get("sections") or []
                if upload_store is not None and self.upload_section not in forced_sections:
                    forced_sections = [self.upload_section] + forced_sections
                for section in explicit_sections:
                    if section not in forced_sections:
                        forced_sections.append(section)
                routing["sections"] = forced_sections

            routing_info["needs_vectorstore"] = routing.get("needs_vectorstore", True)
            routing_info["reason"] = routing.get("reason", "")

            if not routing.get("needs_vectorstore", True):
                response = direct_chain.invoke({"chat_history": chat_history, "input": user_input})
                return response.content if hasattr(response, "content") else str(response)

            target_sections = routing.get("sections") or list(active_stores.keys())
            valid_sections = [s for s in target_sections if s in active_stores]

            if not valid_sections:
                missing_explicit = [s for s in explicit_sections if s not in active_stores]
                if missing_explicit:
                    routing_info["reason"] = f"Requested section(s) not found: {', '.join(missing_explicit)}."
                    return (
                        f"The requested data store(s) — {', '.join(missing_explicit)} — aren't available yet. "
                        "An admin needs to add PDFs to that folder and rebuild the index first."
                    )
                routing_info["reason"] = "Router did not select a valid section."
                return "I could not identify a relevant knowledge base for your question. Could you rephrase it?"

            routing_info["sections"] = valid_sections

            all_retrieved_docs = []
            for section in valid_sections:
                # Give the attached PDF a slightly larger k — it's usually
                # the one thing the user actually wants grounded, and it's
                # a private, small per-session index anyway.
                k = 4 if section == self.upload_section else 3
                retriever = active_stores[section].as_retriever(search_kwargs={"k": k})
                docs = retriever.invoke(optimized_query)
                for doc in docs:
                    doc.metadata["retrieved_from"] = section
                all_retrieved_docs.extend(docs)

            all_retrieved_docs = [d for d in all_retrieved_docs if d.page_content and d.page_content.strip()]
            if not all_retrieved_docs:
                return "I could not find relevant information in the knowledge base for this question."

            answer, attempts = "", 0
            while not answer.strip():
                if attempts == 2:
                    return "I found relevant context but could not formulate a response. Try rephrasing."
                raw_answer = question_answer_chain.invoke({
                    "chat_history": chat_history, "input": user_input,
                    "context": all_retrieved_docs, "sources_searched": ", ".join(valid_sections),
                })
                if hasattr(raw_answer, "content"):
                    answer = raw_answer.content
                elif isinstance(raw_answer, dict):
                    answer = raw_answer.get("answer") or raw_answer.get("output") or ""
                else:
                    answer = str(raw_answer)
                attempts += 1
            return answer

        rag_router_chain = RunnablePassthrough() | route_and_retrieve

        self.conversation_chain = RunnableWithMessageHistory(
            rag_router_chain,
            self.get_session_history,
            input_messages_key="input",
            history_messages_key="chat_history",
        )

    # ── Public entry point used by the Flask chat endpoint ──────────────
    def ask(self, runtime_session_id: str, user_question: str,
            selected_stores: list = None, use_hate_speech: bool = False) -> dict:
        """Runs the full pipeline for one user turn. Returns
        {"answer": str, "searched": [str, ...]}."""
        selected_stores = selected_stores or []
        result = {"answer": "", "searched": [], "references": [], "moderation": None}

        if use_hate_speech:
            result["moderation"] = self.analyze_hate_speech(user_question)

        if "WEB" in selected_stores:
            web_result = self.web_search(user_question)
            answer = web_result["answer"]
            # Keep conversational memory consistent even though this branch
            # bypasses the normal RunnableWithMessageHistory-wrapped chain.
            history = self.get_session_history(runtime_session_id)
            history.add_user_message(user_question)
            history.add_ai_message(answer)
            result["answer"] = answer
            result["references"] = web_result.get("references", [])
            result["searched"] = ["WEB"]
            return result

        if self.conversation_chain is None:
            self._rebuild_chain()

        forced_sections = [s for s in selected_stores if s != "WEB"]
        answer = self.conversation_chain.invoke(
            {
                "input": user_question,
                "runtime_session_id": runtime_session_id,
                "forced_sections": forced_sections,
            },
            config={"configurable": {"session_id": runtime_session_id}},
        )
        if not isinstance(answer, str):
            answer = str(answer)
        result["answer"] = answer
        result["searched"] = list(self.routing_info.get("sections", []))
        return result

