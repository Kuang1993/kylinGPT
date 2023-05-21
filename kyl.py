import streamlit as st
import openai
import requests
import json
import urllib
from PIL import Image
from io import BytesIO
import matplotlib.pyplot as plt

@st.cache_data
def prompt_and_call(api_key, prompt, max_tokens=3000):
    openai.api_key = api_key
    response = openai.Completion.create(
        engine="text-davinci-002",
        prompt=prompt,
        max_tokens=max_tokens
    )
    return response.choices[0].text.strip()

@st.cache_data
def get_unsplash_image_url(keyword):
    url = f"https://source.unsplash.com/960x640/?{keyword}"
    return url

@st.cache_data
def save_image(url, filename):
    urllib.request.urlretrieve(url, filename)
    return filename

@st.cache_data
def draw_image(api_key, prompt):
    openai.api_key = api_key
    response = openai.Image.create(
        prompt=prompt,
        n=1,
        size="720x720"
    )

    # This line is updated according to the response data structure.
    image_url = response['data'][0]['url']

    return image_url


def main():
    st.title("Kylin匡的GPT学术版")
    api_key = st.text_input("Please enter your OpenAI API key: ")

    function_choice = st.selectbox("Please select a function: ",
        ("English text polishing", "Chinese text polishing", "Grammar and spelling check", 
        "English-Chinese translation", "Image search", "Image generation", "Forget previous conversation", "Exit"))

    if function_choice == 'English text polishing':
        english_text = st.text_input("Please enter the English text you want to polish: ")
        st.write(prompt_and_call(api_key, f'Below is a paragraph from an academic paper. Polish the writing to meet the academic style, improve the spelling, grammar, clarity, concision and overall readability. When necessary, rewrite the whole sentence. Furthermore, list all modification and explain the reasons to do so in markdown table. {english_text}'))

    elif function_choice == 'Chinese text polishing':
        chinese_text = st.text_input("Please enter the Chinese text you want to polish: ")
        st.write(prompt_and_call(api_key, f'作为一名中文学术论文写作改进助理，你的任务是改进所提供文本的拼写、语法、清晰、简洁和整体可读性，同时分解长句，减少重复，并提供改进建议。请只提供文本的更正版本，避免包括解释。请编辑以下文本 {chinese_text}'))

    elif function_choice == 'Grammar and spelling check':
        text_to_check = st.text_input("Please enter the text you want to check for grammar and spelling errors: ")
        st.write(prompt_and_call(api_key, f'Can you help me ensure that the grammar and the spelling is correct? Do not try to polish the text, if no mistake is found, tell me that this paragraph is good.If you find grammar or spelling mistakes, please list mistakes you find in a two-column markdown table, put the original text the first column, put the corrected text in the second column and highlight the key words you fixed. {text_to_check}'))

    elif function_choice == 'English-Chinese translation':
        text_to_translate = st.text_input("Please enter the text you want to translate: ")
        st.write(prompt_and_call(api_key, f'Please translate the following English text into Chinese. {text_to_translate}'))

    elif function_choice == 'Image search':
        image_description = st.text_input("Please enter the description of the image you want to search: ")
        keyword = image_description.replace(" ", "+")
        image_url = get_unsplash_image_url(keyword)
        image_filename = f"{keyword}.jpg"
        save_image(image_url, image_filename)
        st.image(image_filename)

    elif function_choice == 'Image generation':
        prompt = st.text_input("Please enter the prompt for image generation: ")
        if prompt:
            img = draw_image(api_key, prompt)
            st.image(img, caption=prompt)

    elif function_choice == 'Forget previous conversation':
        st.write("The previous conversation is forgotten. Please start a new conversation.")

if __name__ == "__main__":
    main()
