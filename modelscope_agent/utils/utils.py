import datetime
import os
import re
import socket
import sys
import traceback
from typing import Literal, Optional, Union
from urllib.parse import unquote_plus, urlparse

import jieba
import json
import json5
from dashscope.common.error import InvalidInput, UploadFileException
from dashscope.utils.oss_utils import OssUtils
from jieba import analyse
from modelscope_agent.constants import ApiNames
from modelscope_agent.schemas import Task
from modelscope_agent.utils.logger import agent_logger as logger
from modelscope_agent.utils.tokenization_utils import count_tokens


def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # doesn't even have to be reachable
        s.connect(('10.255.255.255', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP


def print_traceback():
    logger.error(''.join(traceback.format_exception(*sys.exc_info())))


def has_chinese_chars(data) -> bool:
    text = f'{data}'
    return len(re.findall(r'[\u4e00-\u9fff]+', text)) > 0


def get_current_date_str(
    lang: Literal['en', 'zh'] = 'en',
    hours_from_utc: Optional[int] = None,
) -> str:
    if hours_from_utc is None:
        cur_time = datetime.datetime.now()
    else:
        cur_time = datetime.datetime.utcnow() + datetime.timedelta(
            hours=hours_from_utc)
    if lang == 'en':
        date_str = 'Current date: ' + cur_time.strftime('%A, %B %d, %Y')
    elif lang == 'zh':
        cur_time = cur_time.timetuple()
        date_str = f'当前时间：{cur_time.tm_year}年{cur_time.tm_mon}月{cur_time.tm_mday}日，星期'
        date_str += ['一', '二', '三', '四', '五', '六', '日'][cur_time.tm_wday]
        date_str += '。'
    else:
        raise NotImplementedError
    return date_str


def save_text_to_file(path, text):
    try:
        with open(path, 'w', encoding='utf-8') as fp:
            fp.write(text)
        return 'SUCCESS'
    except Exception as ex:
        print_traceback()
        return ex


def read_text_from_file(path):
    with open(path, 'r', encoding='utf-8') as file:
        file_content = file.read()
    return file_content


ignore_words = [
    '', ' ', '\t', '\n', '\\', 'is', 'are', 'am', 'what', 'how', '的', '吗', '是',
    '了', '啊', '呢', '怎么', '如何', '什么', '？', '?', '！', '!', '“', '”', '‘', '’',
    "'", "'", '"', '"', ':', '：', '讲了', '描述', '讲', '说说', '讲讲', '介绍', '总结下',
    '总结一下', '文档', '文章', '文稿', '稿子', '论文', 'PDF', 'pdf', '这个', '这篇', '这', '我',
    '帮我', '那个', '下', '翻译'
]


def get_split_word(text):
    text = text.lower()
    _wordlist = jieba.lcut(text.strip())
    wordlist = []
    for x in _wordlist:
        if x in ignore_words:
            continue
        wordlist.append(x)
    return wordlist


def get_keyword_by_llm(text):
    try:
        res = json5.loads(text)
    except Exception:
        return get_split_word(text)

    # json format
    _wordlist = []
    try:
        if 'keywords_zh' in res and isinstance(res['keywords_zh'], list):
            _wordlist.extend([kw.lower() for kw in res['keywords_zh']])
        if 'keywords_en' in res and isinstance(res['keywords_en'], list):
            _wordlist.extend([kw.lower() for kw in res['keywords_en']])
        wordlist = []
        for x in _wordlist:
            if x in ignore_words:
                continue
            wordlist.append(x)
        wordlist.extend(get_split_word(res['text']))
        return wordlist
    except Exception:
        return get_split_word(text)


def get_key_word(text):
    text = text.lower()
    _wordlist = analyse.extract_tags(text)
    wordlist = []
    for x in _wordlist:
        if x in ignore_words:
            continue
        wordlist.append(x)
    print('wordlist: ', wordlist)
    return wordlist


def get_last_one_line_context(text):
    lines = text.split('\n')
    n = len(lines)
    res = ''
    for i in range(n - 1, -1, -1):
        if lines[i].strip():
            res = lines[i]
            break
    return res


def extract_urls(text):
    pattern = re.compile(r'https?://\S+')
    urls = re.findall(pattern, text)
    return urls


def extract_obs(text):
    k = text.rfind('\nObservation:')
    j = text.rfind('\nThought:')
    obs = text[k + len('\nObservation:'):j]
    return obs.strip()


def extract_code(text):
    # Match triple backtick blocks first
    triple_match = re.search(r'```[^\n]*\n(.+?)```', text, re.DOTALL)
    if triple_match:
        text = triple_match.group(1)
    else:
        try:
            text = json5.loads(text)['code']
        except Exception:
            print_traceback()
    # If no code blocks found, return original text
    return text


def parse_latest_plugin_call(text):
    plugin_name, plugin_args = '', ''
    i = text.rfind('\nAction:')
    j = text.rfind('\nAction Input:')
    k = text.rfind('\nObservation:')
    if 0 <= i < j:  # If the text has `Action` and `Action input`,
        if k < j:  # but does not contain `Observation`,
            # then it is likely that `Observation` is ommited by the LLM,
            # because the output text may have discarded the stop word.
            text = text.rstrip() + '\nObservation:'  # Add it back.
        k = text.rfind('\nObservation:')
        plugin_name = text[i + len('\nAction:'):j].strip()
        plugin_args = text[j + len('\nAction Input:'):k].strip()
        text = text[:k]
    return plugin_name, plugin_args, text


# TODO: Say no to these ugly if statements.
def format_answer(text):
    action, action_input, output = parse_latest_plugin_call(text)
    if 'code_interpreter' in text:
        rsp = ''
        code = extract_code(action_input)
        rsp += ('\n```py\n' + code + '\n```\n')
        obs = extract_obs(text)
        if '![fig' in obs:
            rsp += obs
        return rsp
    elif 'image_gen' in text:
        # get url of FA
        # img_urls = URLExtract().find_urls(text.split("Final Answer:")[-1].strip())
        obs = text.split('Observation:')[-1].split('\nThought:')[0].strip()
        img_urls = []
        if obs:
            logger.info(repr(obs))
            try:
                obs = json5.loads(obs)
                img_urls.append(obs['image_url'])
            except Exception:
                print_traceback()
                img_urls = []
        if not img_urls:
            img_urls = extract_urls(text.split('Final Answer:')[-1].strip())
        logger.info(img_urls)
        rsp = ''
        for x in img_urls:
            rsp += '\n![picture](' + x.strip() + ')'
        return rsp
    else:
        return text.split('Final Answer:')[-1].strip()


FILE_PATH_SCHEMA = 'file://'


def get_upload_url(model: str, file_to_upload: str, api_key: str):
    """This function is used to convert local file to get its oss url.

    Args:
        model(str): Theoretically, you can set this parameter freely. It will only affect
                    the information of the oss url and will not affect the function.
        file_to_upload(str): the local file path which you need to convert to oss url.And it should
                            start with 'file://'.
        api_key(str): dashscope_api_key which you have set in environment.

    Returns:
        An oss type url.

    Raises:
        InvalidInput: the file path you upload is not exists.
    """
    if file_to_upload.startswith(FILE_PATH_SCHEMA):
        parse_result = urlparse(file_to_upload)
        if parse_result.netloc:
            file_path = parse_result.netloc + unquote_plus(parse_result.path)
        else:
            file_path = unquote_plus(parse_result.path)
        if os.path.exists(file_path):
            file_url = OssUtils.upload(
                model=model, file_path=file_path, api_key=api_key)
            if file_url is None:
                raise UploadFileException('Uploading file: %s failed'
                                          % file_to_upload)
            return file_url
        else:
            raise InvalidInput('The file: %s is not exists!' % file_path)
    return None


def check_and_limit_input_length(check_body: Union[list, str],
                                 max_length: int) -> str:
    """
    Check the input length and limit the length,

    Args:
        check_body: the input to be checked, should be a list of message or single prompt string
        max_length: the maximum length of the check_body

    Returns:
        the output with the length limited
    """
    if isinstance(check_body, str):
        if len(check_body) <= max_length:
            return check_body
        check_result = check_body[:max_length]
        return check_result
    else:
        # limit the length by limit the history of message from far to near
        used_length = 0
        output_messages = []
        start_index = 0
        if check_body[0]['role'] == 'system':
            output_messages.append(check_body[0])
            used_length += count_tokens(check_body[0]['content'])
            start_index = 1
        for message in reversed(check_body[start_index:]):
            used_length += count_tokens(message['content'])
            if used_length <= max_length:
                # add to the output messages first index
                output_messages.insert(start_index, message)
            else:
                break
        return output_messages


def get_api_key(api_enum: ApiNames, key=None, **kwargs):
    """

    Args:
        api_enum: enum of api name
        key: default key
        **kwargs: might contain the api name

    Returns:

    """
    api_key = ''
    if key is not None:
        if kwargs.get(api_enum.name, '') != '':
            if key != kwargs.get(api_enum.name):
                # use runtime key instead of init key
                api_key = kwargs.get(api_enum.name)
        else:
            api_key = key
    else:
        api_key = kwargs.get(api_enum.name, os.environ.get(api_enum.value, ''))

    assert api_key != '', f'{api_enum.name} must be acquired'
    return api_key


def parse_code(text: str, lang: str = '') -> str:
    pattern = rf'```{lang}.*?\s+(.*?)```'
    match = re.search(pattern, text, re.DOTALL)
    if match:
        code = match.group(1)
    else:
        if lang == 'json':
            try:
                # 成功解析则返回
                json5.loads(text)
                return text
            except ValueError as e:
                logger.error(f'json parse error: {e}')
                pass
        logger.error(f'{pattern} not match following text:')
        logger.error(text)
        raise Exception('Code Pattern Not Matched')
    return code
