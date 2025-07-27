import os

import pytest
from modelscope_agent.memory import MemoryWithRag

IS_FORKED_PR = os.getenv('IS_FORKED_PR', 'false') == 'true'


@pytest.mark.skipif(IS_FORKED_PR, reason='only run modelscope-agent main repo')
def test_memory_with_rag_simple():

    memory = MemoryWithRag(
        urls=['tests/samples/常见QA.pdf'],
        use_knowledge_cache=False,
    )

    summary_str = memory.run(query='高德天气api怎么申请')
    print(summary_str)
    assert 'https://lbs.amap.com/api/javascript-api-v2/guide/services/weather' in summary_str


@pytest.mark.skipif(IS_FORKED_PR, reason='only run modelscope-agent main repo')
def test_memory_with_rag_update():
    memory = MemoryWithRag(use_knowledge_cache=False)

    summary_str = memory.run(
        query='模型大文件上传失败怎么办', url=['tests/samples/modelscope_qa_2.txt'])
    print(summary_str)
    assert 'git-lfs' in summary_str


@pytest.mark.skipif(IS_FORKED_PR, reason='only run modelscope-agent main repo')
def test_memory_with_rag_multi_sources():

    memory = MemoryWithRag(
        urls=['tests/samples/modelscope_qa_2.txt', 'tests/samples/常见QA.pdf'],
        use_knowledge_cache=False,
    )

    summary_str = memory.run('高德天气api怎么申请')
    print(summary_str)
    assert 'https://lbs.amap.com/api/javascript-api-v2/guide/services/weather' in summary_str


@pytest.mark.skip
def test_memory_with_rag_cache():
    MemoryWithRag(
        urls=['tests/samples/modelscope_qa_2.txt', 'tests/samples/常见QA.pdf'],
        storage_path='./tmp/',
        use_knowledge_cache=False,
    )

    memory = MemoryWithRag(
        storage_path='./tmp/',
        use_knowledge_cache=True,
    )
    summary_str = memory.run('模型大文件上传失败怎么办')
    print(summary_str)
    assert 'git-lfs' in summary_str


@pytest.mark.skipif(IS_FORKED_PR, reason='only run modelscope-agent main repo')
def test_memory_with_rag_custom():
    from llama_index.retrievers.bm25 import BM25Retriever
    from llama_index.readers.json import JSONReader
    from llama_index.core.extractors import TitleExtractor

    memory = MemoryWithRag(
        urls=['tests/samples/modelscope_qa_2.txt'],
        storage_path='./tmp/',
        memory_path='./tmp/',
        use_knowledge_cache=False,
        retriever=BM25Retriever,
        loaders={'.json': JSONReader},
        post_processors=[],
        transformations=[TitleExtractor])
    summary_str = memory.run('模型大文件上传失败怎么办')
    print(summary_str)
    assert 'git-lfs' in summary_str


@pytest.mark.skipif(IS_FORKED_PR, reason='only run modelscope-agent main repo')
def test_memory_with_rag_multi_modal():
    memory = MemoryWithRag(
        urls=['tests/samples/rag.png'],
        use_knowledge_cache=False,
    )

    summary_str = memory.run('根据rag的流程图，loading的后一步是什么？')
    print(summary_str)
    assert 'indexing' in summary_str or 'Indexing' in summary_str or '索引' in summary_str


@pytest.mark.skipif(IS_FORKED_PR, reason='only run modelscope-agent main repo')
def test_memory_with_rag_multi_modal_ms():
    from modelscope_agent.rag.reader.image import OcrParser
    memory = MemoryWithRag(
        urls=['tests/samples/rag.png'],
        use_knowledge_cache=False,
        image_parser=OcrParser(),
    )

    summary_str = memory.run('根据rag的流程图，loading的后一步是什么？')
    print(summary_str)
    assert 'indexing' in summary_str or 'Indexing' in summary_str or '索引' in summary_str


@pytest.mark.skipif(IS_FORKED_PR, reason='only run modelscope-agent main repo')
def test_memory_with_rag_no_use_llm():
    memory = MemoryWithRag(use_knowledge_cache=False)

    summary_str = memory.run(
        query='模型大文件上传失败怎么办',
        url=['tests/samples/modelscope_qa_2.txt'],
        use_llm=False)
    print(summary_str)
    assert 'file_path' in summary_str
    assert 'git-lfs' in summary_str


@pytest.mark.skip
def test_memory_with_rag_mongodb_storage():
    # $ mongod --dbpath ./mongodb --logpath ./mongo.log --fork
    import os
    import shutil
    from llama_index.storage.docstore.mongodb import MongoDocumentStore
    from llama_index.storage.index_store.mongodb import MongoIndexStore
    MONGO_URI = os.environ.get('MONGO_URI', 'mongodb://localhost')
    cache_dir = './tmp'

    MemoryWithRag(
        urls=['tests/samples/modelscope_qa_1.txt'],
        storage_path=cache_dir,
        use_knowledge_cache=True,
        docstore=MongoDocumentStore.from_uri(MONGO_URI),
        index_store=MongoIndexStore.from_uri(MONGO_URI))

    # clean local cache
    if os.path.exists(cache_dir):
        shutil.rmtree(cache_dir)

    memory = MemoryWithRag(
        use_knowledge_cache=True,
        storage_path=cache_dir,
        docstore=MongoDocumentStore.from_uri(MONGO_URI),
        index_store=MongoIndexStore.from_uri(MONGO_URI))
    summary_str = memory.run('环境安装报错 missing xcrun 怎么办？')
    print(summary_str)
    assert 'xcode-select --install' in summary_str


@pytest.mark.skip
def test_memory_with_rag_mongodb_reader():
    # $ mongod --dbpath ./mongodb --logpath ./mongo.log --fork

    # insert msg
    import pymongo
    client = pymongo.MongoClient()
    db = client['test_db']
    collection = db['myCollection']
    collection.insert_one({
        'content':
        'Alice decided to compile a book of interviews with startup founders.'
    })

    # read from mongodb
    from llama_index.readers.mongodb import SimpleMongoReader
    MONGO_URI = 'mongodb://localhost'
    reader = SimpleMongoReader(uri=MONGO_URI)
    documents = reader.load_data(
        db_name='test_db',
        collection_name='myCollection',
        field_names=['content'])
    memory = MemoryWithRag(use_knowledge_cache=False, documents=documents)

    res = memory.run('Who decided to compile a book?', use_llm=False)
    print(res)
    assert 'Alice' in res


@pytest.mark.skipif(IS_FORKED_PR, reason='only run modelscope-agent main repo')
def test_memory_with_rag_files():
    MemoryWithRag(
        urls=[
            'tests/samples/modelscope_qa_2.txt', 'tests/samples/常见QA.pdf',
            'tests/samples/modelscope_qa_1.txt'
        ],
        storage_path='./tmp/',
        use_knowledge_cache=False,
    )

    memory = MemoryWithRag(
        storage_path='./tmp/',
        use_knowledge_cache=True,
    )
    files = ['modelscope_qa_2.txt', '常见QA.pdf']
    summary_str = memory.run('多卡环境，如何指定卡推理？', url=files)
    print(summary_str)
    assert 'gpu:0' in summary_str
