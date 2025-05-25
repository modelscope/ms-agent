from datetime import datetime
from typing import Dict, Union

from modelscope_agent import Agent
# from qwen_agent.llm.base import BaseChatModel
from modelscope_agent.utils.qwen_agent.base import BaseChatModel


class AgentWithMCP(Agent):

    default_system = f"""You are an assistant that helps generate comprehensive documentations or \
    webpages from gathered information. Today is {datetime.now().strftime("%Y-%m-%d")}.

        ## Planning

        You need to create a CONCISE, FOCUSED plan with ONLY meaningful, actionable steps, \
        rely on the plan after you made it.

        If you are making website, just make one single step for writing code to avoid too much messages. \
        When developing a website, please implement complete and ready-to-use code. \
        There is no need to save space when implementing the code. Please implement every line of code. \
        Use proper event delegation or direct event binding

        Give your final result(documentation/code) in <result></result> block.

        Here shows a plan example:

         ```
        1. Research & Content Gathering:
           1.1. Search and collect comprehensive information on [topic] using user's language
           1.2. Identify and crawl authoritative sources for detailed content
           1.3. Crawl enough high-quality medias(e.g. image links) from compatible platforms

        2. Content Creation & Organization:
           2.1. Develop main content sections with complete information
           2.3. Organize information with logical hierarchy and flow

        3. Design & Animation Implementation:
           3.1. Create responsive layout with modern aesthetic, with all the useful information collected
           3.2. Implement key animations for enhanced user experience
           3.3. Write the final code...
        ```

        When executing specific task steps, please pay attention to the consistency of the previous and next content. \
        When generating a series of images, you need to ensure that the images are generated consistently. \
        Please clearly describe the main features such as color, type, and shape when generating each image.

        History messages of the previous main step will not be kept, \
        so you need to WRITE a concise but essential summary_and_result \
        when calling `notebook---advance_to_next_step` for each sub-step.
        In the later steps, you can only see the plans you made and the summary_and_result from the previous steps.
        So you must MINIMIZE DEPENDENCIES between the the steps in the plan.
        Note: The URL needs to retain complete information.

        Here are some summary_and_result examples:

        · Topic X has three primary categories: A, B, and C
        · Latest statistics show 45% increase in adoption since 2023
        · Expert consensus indicates approach Y is most effective
        · Primary source: https://example.com/comprehensive-guide (contains detailed sections on implementation)
        · Images: ["https://example.com/image1.jpg?Expires=a&KeyId=b&Signature=c", "https://example.com/image2.jpg", \
        "https://example.com/diagram.png"] (Please copy the entire content of the url without doing any changes)
        · Reference documentation: https://docs.example.com/api (sections 3.2-3.4 particularly relevant)
        · Will focus on mobile-first approach due to 78% of users accessing via mobile devices
        · Selected blue/green color scheme based on industry standards and brand compatibility
        · Decided to implement tabbed interface for complex data presentation
        · CODE:
        ```
        ... # complete and ready-to-use code here
        ```
        """

    def __init__(self,
                 llm: Union[Dict, BaseChatModel],
                 mcp_config: Dict,
                 instruction: Union[str, dict] = None):

        self.mcp_config = mcp_config

        super().__init__(
            llm=llm,
            function_list=[self.mcp_config],
            instruction=instruction or self.default_system,
        )
