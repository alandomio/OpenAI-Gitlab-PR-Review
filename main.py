import os
import json
import requests
from flask import Flask, request
import openai


app = Flask(__name__)
openai.api_key = os.environ.get("OPENAI_API_KEY")
gitlab_token = os.environ.get("GITLAB_TOKEN")
gitlab_url = os.environ.get("GITLAB_URL")

api_base = os.environ.get("AZURE_OPENAI_API_BASE")
if api_base != None:
    openai.api_base = api_base

openai.api_version = os.environ.get("AZURE_OPENAI_API_VERSION")
if openai.api_version != None:
    openai.api_type = "azure"

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get("X-Gitlab-Token") != os.environ.get("EXPECTED_GITLAB_TOKEN"):
        return "Unauthorized", 403
    payload = request.json
    if payload.get("object_kind") == "merge_request":
        project_id = payload["project"]["id"]
        mr_id = payload["object_attributes"]["iid"]
        changes_url = f"{gitlab_url}/projects/{project_id}/merge_requests/{mr_id}/changes"

        print(changes_url, flush=True)

        headers = {"Private-Token": gitlab_token}
        print(headers, flush=True)
        print("CIAO", flush=True)
        response = requests.get(changes_url, headers=headers)
 
        mr_changes = response.json()
        target_branch = mr_changes["target_branch"]

        diffs = []
        files_content = ''

        for change in mr_changes["changes"]:
            diffs.append(change["diff"])
            file = change["new_path"]
            file_url = f"{gitlab_url}/projects/{project_id}/repository/files/{file}/raw?ref={target_branch}"
            file_response = requests.get(file_url, headers=headers)
            print(file_response)
            
            if file_response.status_code == 200:
                files_content += "\n\nFilename: {file}\n" + file_response.text

        pre_prompt = "Review the git diff of a recent commit, focusing on clarity, structure, tests, standard compliance and security. Ensure to assess how the changes impact the overall project. i will include also the content of the files that have been changed."

        questions = """
        Questions:
        1. What are the key changes and the reasons for these modifications?.
        2. Is the new/modified code logically structured and easy to follow? Highlight any part that could be simplified.
        3. Are the comments sufficient and helpful? Do the names of variables, functions, and classes accurately reflect their purpose??
        4. Identify specific areas where complexity could be reduced. What refactoring would you suggest?
        5. Do you see any common bug patterns, off-by-one errors or improper error handling?
        6. Review the code for common security vulnerabilities, like injection or missed input validation. Are there any deviations from secure coding practices?
        7. How well does the code align with established best practices in our field? Suggest any improvements.
        8. Are there adequate tests for the new/modified code? Are any critical paths left untested?
        9. Do you have any additional suggestions for overall improvement not covered by the previous questions, for example style improvement, formatting?
        10. Confirm that the changes are consistent and the branch is ready to be merged.
        """

        messages = [
            {"role": "system", "content": "You are a senior developer reviewing code changes."},
            {"role": "user", "content": f"{pre_prompt}\n\n{''.join(diffs)}\n\n{files_content}\n\n{questions}"},
            {"role": "assistant", "content": "Response must be markdown formatted. Include a concise version of each question in your response."},
        ]

        message_lengths = [len(message["content"]) for message in messages]
        total_length = sum(message_lengths)

        try:
            completions = openai.ChatCompletion.create(
                deployment_id=os.environ.get("OPENAI_API_MODEL"),
                model=os.environ.get("OPENAI_API_MODEL") or "gpt-3.5-turbo",
                temperature=0.1,
                stream=False,
                messages=messages
            )
            # get the token number of the first completion
            tokens_used = completions['usage']['total_tokens']
            print(f"Tokens used: {tokens_used}")
            cost = tokens_used * 5 / 1000000
            
            answer = completions.choices[0].message["content"].strip()
            answer += "\n\n > This comment was generated by an artificial intelligence duck."
            answer += "\n > Tokens used: " + str(tokens_used) + " Cost: " + str(cost) + " USD"
            answer += "\n > Context length: " + str(total_length) + " bytes"
        except Exception as e:
            print(e)
            answer = "I'm sorry, I'm not feeling well today. Please ask a human to review this MR."
            answer += "\n\nThis comment was generated by an artificial intelligence duck."
            answer += "\n\nError: " + str(e)

        print(answer)
        comment_url = f"{gitlab_url}/projects/{project_id}/merge_requests/{mr_id}/notes"
        comment_payload = {"body": answer}
        comment_response = requests.post(comment_url, headers=headers, json=comment_payload)
    elif payload.get("object_kind") == "push":
        project_id = payload["project_id"]
        commit_id = payload["after"]
        commit_url = f"{gitlab_url}/projects/{project_id}/repository/commits/{commit_id}/diff"

        headers = {"Private-Token": gitlab_token}
        response = requests.get(commit_url, headers=headers)
        changes = response.json()

        changes_string = ''.join([str(change) for change in changes])

        pre_prompt = "Review the git diff of a recent commit, focusing on clarity, structure, and security."

        questions = """
        Questions:
        1. Summarize changes (Changelog style).
        2. Clarity of added/modified code?
        3. Comments and naming adequacy?
        4. Simplification without breaking functionality? Examples?
        5. Any bugs? Where?
        6. Potential security issues?
        """

        messages = [
            {"role": "system", "content": "You are a senior developer reviewing code changes from a commit."},
            {"role": "user", "content": f"{pre_prompt}\n\n{changes_string}{questions}"},
            {"role": "assistant", "content": "Respond in markdown for GitLab. Include concise versions of questions in the response."},
        ]

        print(messages)
        try:
            completions = openai.ChatCompletion.create(
                deployment_id=os.environ.get("OPENAI_API_MODEL"),
                model=os.environ.get("OPENAI_API_MODEL") or "gpt-3.5-turbo",
                temperature=0.7,
                stream=False,
                messages=messages
            )
            answer = completions.choices[0].message["content"].strip()
            answer += "\n\nFor reference, i was given the following questions: \n"
            for question in questions.split("\n"):
                answer += f"\n{question}"
            answer += "\n\nThis comment was generated by an artificial intelligence duck."
        except Exception as e:
            print(e)
            answer = "I'm sorry, I'm not feeling well today. Please ask a human to review this code change."
            answer += "\n\nThis comment was generated by an artificial intelligence duck."
            answer += "\n\nError: " + str(e)

        print(answer)
        comment_url = f"{gitlab_url}/projects/{project_id}/repository/commits/{commit_id}/comments"
        comment_payload = {"note": answer}
        comment_response = requests.post(comment_url, headers=headers, json=comment_payload)

    return "OK", 200


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
