# Copyright (c) ModelScope Contributors. All rights reserved.
from ms_agent.callbacks.input_callback import InputCallback
from ms_agent.callbacks.repetition_guard import RepetitionGuardCallback

callbacks_mapping = {
    'input_callback': InputCallback,
    'repetition_guard': RepetitionGuardCallback,
}
