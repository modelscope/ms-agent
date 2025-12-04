import os
import uuid


class GoogleImageGenerator:

    def __init__(self, config, temp_dir):
        self.config = config
        self.temp_dir = temp_dir
        os.makedirs(self.temp_dir, exist_ok=True)

    async def generate_image(self,
                             positive_prompt,
                             negative_prompt=None,
                             **kwargs):
        # TODO not tested
        from google import genai
        image_generator = self.config.tools.image_generator
        api_key = image_generator.api_key
        model_id = image_generator.model
        assert api_key is not None
        task_id = str(uuid.uuid4())[:8]
        output_file = os.path.join(self.temp_dir, f'{task_id}.png')
        if api_key:
            client = genai.Client(api_key=api_key)
        else:
            client = genai.Client()

        response = client.models.generate_content(
            model=model_id,
            contents=[positive_prompt],
        )

        for part in response.parts:
            if part.inline_data is not None:
                image = part.as_image()
                image.save(output_file)
                return output_file

        return f'No image returned, check response.parts: {response.parts}'
