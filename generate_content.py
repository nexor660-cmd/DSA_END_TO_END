import os
import subprocess
import google.generativeai as genai

# Configure AI
genai.configure(api_key=os.environ["GEMINI_API_KEY"])
model = genai.GenerativeModel('gemini-1.5-flash')

# Get latest commit message
commit_msg = subprocess.check_output(['git', 'log', '-1', '--pretty=%B']).decode('utf-8').strip()

prompt = f"""
I just pushed this update to my project: "{commit_msg}"
Write 3 things:
1. README: A 2-sentence summary of this update for a 'Latest Updates' section.
2. Twitter: A short, engaging, humanized 'build in public' tweet (under 280 chars) with hashtags.
3. LinkedIn: A slightly longer, professional yet enthusiastic post about this progress.
Output EXACTLY in this format:
[README]
<text>
[TWITTER]
<text>
[LINKEDIN]
<text>
"""

response = model.generate_content(prompt).text

# Parse response
readme_text = response.split('[README]')[1].split('[TWITTER]')[0].strip()
twitter_text = response.split('[TWITTER]')[1].split('[LINKEDIN]')[0].strip()
linkedin_text = response.split('[LINKEDIN]')[1].strip()

# 1. Update README.md
with open('README.md', 'a') as f:
    f.write(f"\n- **Update:** {readme_text}\n")

# 2. Save Social Drafts for GitHub Action to read
issue_body = f"## 🐦 Twitter / X Draft\n\n```text\n{twitter_text}\n```\n\n---\n\n## 💼 LinkedIn Draft\n\n```text\n{linkedin_text}\n```\n\n*Review, copy, and post manually!*"
with open('draft.md', 'w') as f:
    f.write(issue_body)