import asyncio
import shutil
import unittest

from ms_agent.rag.llama_index_rag import LlamaIndexRAG
from omegaconf import DictConfig

from modelscope.utils.test_utils import test_level


class LlamaIndexRagTest(unittest.TestCase):

    def setUp(self):
        pass

    def tearDown(self):
        shutil.rmtree('./llama_index', ignore_errors=True)

    async def retrieve(self):
        config = DictConfig({
            'rag': {
                'name': 'LlamaIndexRAG',
                'embedding': 'Qwen/Qwen3-Embedding-0.6B',
                'retrieve_only': True,
            }
        })
        rag = LlamaIndexRAG(config=config)

        documents = [
            """
            人工智能（Artificial Intelligence, AI）是计算机科学的一个分支，
            它企图了解智能的实质，并生产出一种新的能以人类智能相似的方式做出反应的智能机器。
            该领域的研究包括机器人、语言识别、图像识别、自然语言处理和专家系统等。
            人工智能的发展历程可以追溯到20世纪50年代，经历了多次起伏。
            """, """
            机器学习是人工智能的一个重要分支，是实现人工智能的一个途径。
            机器学习算法是一类从数据中自动分析获得规律，并利用规律对未知数据进行预测的算法。
            常见的机器学习算法包括线性回归、决策树、支持向量机、神经网络等。
            机器学习可以分为监督学习、无监督学习和强化学习三大类。
            """, """
            深度学习是机器学习的一个子领域，它基于人工神经网络进行学习。
            深度学习通过多层神经网络来学习数据的高层次特征表示。
            深度学习在图像识别、语音识别、自然语言处理等领域取得了重大突破。
            深度学习的核心是神经网络，特别是深度神经网络。
            """, """
            自然语言处理（Natural Language Processing, NLP）是人工智能的一个重要应用领域。
            NLP的目标是让计算机能够理解、解释和生成人类语言。
            主要技术包括词法分析、句法分析、语义分析、文本分类、情感分析等。
            现代NLP大量使用深度学习技术，如Transformer、BERT等模型。
            """
        ]

        await rag.add_documents(documents)
        query = '什么是深度学习'
        result1 = await rag.retrieve(query, top_k=3)
        for i, result in enumerate(result1):
            print(f"{i + 1}. 相似度: {result['score']:.4f}")
            print(f"   内容: {result['text'][:100]}...")
            print()

        await rag.save_index('./my_index')
        new_rag = LlamaIndexRAG(config)
        await new_rag.load_index('./my_index')
        result2 = await new_rag.retrieve(query, top_k=3)
        return result1, result2

    @unittest.skipUnless(test_level() >= 1, 'skip test in current test level')
    def test_retrieve(self):
        result1, result2 = asyncio.run(self.retrieve())
        self.assertEqual(len(result1), len(result2))
        self.assertEqual(result1[0]['text'], result2[0]['text'])


if __name__ == '__main__':
    unittest.main()
