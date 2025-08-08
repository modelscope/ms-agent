# import os
# import unittest
#
# from ms_agent.tools.docling.doc_loader import DocLoader
#
# from modelscope.utils.test_utils import test_level
#
#
# class TestExtractImage(unittest.TestCase):
#     base_dir: str = os.path.dirname(os.path.abspath(__file__))
#     absolute_path_img_url: str = 'https://www.chinahighlights.com/hangzhou/food-restaurant.htm'
#     relative_path_img_url: str = 'https://github.com/asinghcsu/AgenticRAG-Survey'
#     figure_tag_img_url: str = 'https://blogs.nvidia.com/blog/what-is-retrieval-augmented-generation/'
#     data_uri_img_url: str = 'https://arxiv.org/html/2505.16120v1'
#
#     @unittest.skipUnless(test_level() >= 2, 'skip test in current test level')
#     def test_absolute_path_img(self):
#         save_dir = os.path.join(self.base_dir, 'absolute_path_img')
#         if not os.path.exists(save_dir):
#             os.makedirs(save_dir)
#         doc_loader = DocLoader()
#         doc_results = doc_loader.load(
#             urls_or_files=[self.absolute_path_img_url])
#         for idx, pic in enumerate(doc_results[0].pictures):
#             print(f'Picture: {pic.self_ref} ...')
#             if pic.image:
#                 pic.image.pil_image.save(
#                     os.path.join(save_dir, 'picture_' + str(idx) + '.png'))
#         assert len(
#             doc_results[0].pictures) > 0, 'No pictures found in the document.'
#
#     @unittest.skipUnless(test_level() >= 2, 'skip test in current test level')
#     def test_relative_path_img(self):
#         save_dir = os.path.join(self.base_dir, 'relative_path_img')
#         if not os.path.exists(save_dir):
#             os.makedirs(save_dir)
#         doc_loader = DocLoader()
#         doc_results = doc_loader.load(
#             urls_or_files=[self.relative_path_img_url])
#         for idx, pic in enumerate(doc_results[0].pictures):
#             print(f'Picture: {pic.self_ref} ...')
#             if pic.image:
#                 pic.image.pil_image.save(
#                     os.path.join(save_dir, 'picture_' + str(idx) + '.png'))
#         assert len(
#             doc_results[0].pictures) > 0, 'No pictures found in the document.'
#
#     @unittest.skipUnless(test_level() >= 2, 'skip test in current test level')
#     def test_figure_tag_img(self):
#         save_dir = os.path.join(self.base_dir, 'figure_tag_img')
#         if not os.path.exists(save_dir):
#             os.makedirs(save_dir)
#         doc_loader = DocLoader()
#         doc_results = doc_loader.load(urls_or_files=[self.figure_tag_img_url])
#         for idx, pic in enumerate(doc_results[0].pictures):
#             print(f'Picture: {pic.self_ref} ...')
#             if pic.image:
#                 pic.image.pil_image.save(
#                     os.path.join(save_dir, 'picture_' + str(idx) + '.png'))
#         assert len(
#             doc_results[0].pictures) > 0, 'No pictures found in the document.'
#
#     @unittest.skipUnless(test_level() >= 2, 'skip test in current test level')
#     def test_data_uri_img(self):
#         save_dir = os.path.join(self.base_dir, 'data_uri_img')
#         if not os.path.exists(save_dir):
#             os.makedirs(save_dir)
#         doc_loader = DocLoader()
#         doc_results = doc_loader.load(urls_or_files=[self.data_uri_img_url])
#         for idx, pic in enumerate(doc_results[0].pictures):
#             print(f'Picture: {pic.self_ref} ...')
#             if pic.image:
#                 pic.image.pil_image.save(
#                     os.path.join(save_dir, 'picture_' + str(idx) + '.png'))
#         assert len(
#             doc_results[0].pictures) > 0, 'No pictures found in the document.'
#
#
# if __name__ == '__main__':
#     unittest.main()
