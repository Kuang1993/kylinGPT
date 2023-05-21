# KylinGPT

KylinGPT🤖 是一个基于OpenAI的GPT模型的应用，它包括中英文学术润色、翻译、图片搜索以及图片生成等功能。

## Get Started✈

在克隆(git clone)该仓库后，你可以使用以下命令安装所有的依赖🦄：

```
pip install -r requirements.txt
```
你可以在cmd命令行使用以下命令来运行该应用🦾：
```
streamlit run kylinGPT.py
```
项目结构🐓
```
kylinGPT.py: 主应用程序文件
README.md: 项目说明和指南
requirements.txt: 项目依赖列表
```
参考与学习🗃
```
代码中参考了很多其他优秀项目中的设计，主要包括：

# 借鉴项目1：借鉴了ChuanhuChatGPT中读取OpenAI json的方法、记录历史问询记录的方法以及gradio queue的使用技巧
https://github.com/GaiZhenbiao/ChuanhuChatGPT
# 借鉴项目2：借鉴了ChatGPT 学术优化中的一些prompt（本项目主要目的是降低该项目的使用难度，并增加了Prompt绘图功能）
https://github.com/webwarz/chatgpt
