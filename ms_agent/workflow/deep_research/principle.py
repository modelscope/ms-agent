# flake8: noqa


class Principle:

    def __init__(self, breakdown_prompt: str = None):

        self.breakdown_prompt: str = breakdown_prompt or """\n首先生成一份系统性的分析方案，自上而下breakdown，输出markdown格式：\n
                """

        self.todo_prompt: str = """"\n基于上述breakdown，生成todo list，输出markdown格式，形式必须遵循：\n
                # Title

                ## Main task

                - [ ] xxx

                ---

                ## T1: xxx

                - [ ] T1.1 xxx
                - [ ] T1.2 xxx

                ## T2: xxx

                - [ ] T2.1 xxx
                \n
                """

        self.convert_todo_prompt: str = """
                \n\n将以上markdown格式的todo list转换成python的list格式，字段构成必须遵循以下json格式，且仅输出json数据：
                [
                    {
                        "main_goal": "",
                        "tasks": [
                            {
                                "category": "",
                                "items": [
                                    {"description": "", "completed": false},
                                    {"description": "", "completed": false},
                                    {"description": "", "completed": false}
                                ]
                            },
                            {
                                "category": "",
                                "items": [
                                    {"description": "", "completed": false},
                                    {"description": "", "completed": false}
                                ]
                            }
                        ]
                    }
                ]
                \n"""


class BSGMatrixPrinciple(Principle):

    def __init__(self, breakdown_prompt: str = None):
        super().__init__(breakdown_prompt=breakdown_prompt)

        self.breakdown_prompt = breakdown_prompt or '\n首先使用Boston Matrix Analysis Principle(Boston Consulting Group matrix analysis)来拆解和分析上述问题，输出markdown格式：'


class ParetoPrinciple(Principle):

    def __init__(self, breakdown_prompt: str = None):
        super().__init__(breakdown_prompt=breakdown_prompt)

        self.breakdown_prompt = breakdown_prompt or '\n首先使用Pareto Principle(80/20 Rule)来拆解和分析上述问题，输出markdown格式：'


class MECEPrinciple(Principle):

    def __init__(self, breakdown_prompt: str = None):
        super().__init__(breakdown_prompt=breakdown_prompt)

        self.breakdown_prompt = breakdown_prompt or '\n首先使用MECE原则(Mutually Exclusive and Collectively Exhaustive)来拆解和分析上述问题，输出markdown格式：'


class PyramidPrinciple(Principle):

    def __init__(self, breakdown_prompt: str = None):
        super().__init__(breakdown_prompt=breakdown_prompt)

        self.breakdown_prompt = breakdown_prompt or '\n首先使用金字塔原理(Pyramid Principle)来拆解和分析上述问题，输出markdown格式：'


class SWOTPrinciple(Principle):

    def __init__(self, breakdown_prompt: str = None):
        super().__init__(breakdown_prompt=breakdown_prompt)

        self.breakdown_prompt = breakdown_prompt or '\n首先使用SWOT分析法(SWOT Analysis)来拆解和分析上述问题，输出markdown格式：'


class ValueChainPrinciple(Principle):

    def __init__(self, breakdown_prompt: str = None):
        super().__init__(breakdown_prompt=breakdown_prompt)

        self.breakdown_prompt = breakdown_prompt or '\n首先使用价值链分析(Value Chain Analysis)来拆解和分析上述问题，输出markdown格式：'
