import os
import uuid


class EdgeTTSGenerator:

    def __init__(self, config, temp_dir):
        self.config = config
        self.temp_dir = temp_dir

    async def generate_audio(self, text, **kwargs):
        task_id = str(uuid.uuid4())[:8]
        output_file = os.path.join(self.temp_dir, f'{task_id}.mp3')
        await self.edge_tts_generate(text, output_file, **kwargs)
        return output_file

    @staticmethod
    async def edge_tts_generate(text, output_file, speaker='zh-CN-YunjianNeural', rate='+0%', pitch='+0Hz'):
        import edge_tts
        output_dir = os.path.dirname(output_file) or '.'
        os.makedirs(output_dir, exist_ok=True)
        communicate = edge_tts.Communicate(
            text=text, voice=speaker, rate=rate, pitch=pitch)

        audio_data = b''
        chunk_count = 0
        async for chunk in communicate.stream():
            if chunk['type'] == 'audio':
                audio_data += chunk['data']
                chunk_count += 1

        assert len(audio_data) > 0
        with open(output_file, 'wb') as f:
            f.write(audio_data)
