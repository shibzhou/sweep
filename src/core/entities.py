import json
import re
from typing import ClassVar, Literal, Self, Type
from loguru import logger
from pydantic import BaseModel


class Message(BaseModel):
    role: Literal["system"] | Literal["user"] | Literal["assistant"] | Literal["function"]
    content: str | None = None
    name: str | None = None
    function_call: dict | None = None
    key: str | None = None

    def to_openai(self) -> str:
        obj = {
            "role": self.role,
            "content": self.content,
        }
        if self.function_call:
            obj["function_call"] = self.function_call
        if self.role == "function":
            obj["name"] = self.name
        return obj

class Function(BaseModel):
    class Parameters(BaseModel):
        type: str = "object"
        properties: dict
    name: str
    description: str
    parameters: Parameters

class RegexMatchError(ValueError):
    pass


class RegexMatchableBaseModel(BaseModel):
    _regex: ClassVar[str]

    @classmethod
    def from_string(cls: Type[Self], string: str, **kwargs) -> Self:
        # match = re.search(file_regex, string, re.DOTALL)
        match = re.search(cls._regex, string, re.DOTALL)
        if match is None:
            logger.warning(f"Did not match {string} with pattern {cls._regex}")
            raise RegexMatchError("Did not match")
        return cls(
            **{k: (v if v else "").strip() for k, v in match.groupdict().items()},
            **kwargs,
        )


class FilesToChange(RegexMatchableBaseModel):
    files_to_modify: str
    files_to_create: str
    _regex = r"""<create>(?P<files_to_create>.*)</create>\s*<modify>(?P<files_to_modify>.*)</modify>"""


class FileChangeRequest(RegexMatchableBaseModel):
    filename: str
    instructions: str
    change_type: Literal["modify"] | Literal["create"]
    _regex = r"""^ *`?(?P<filename>\S*)`?:(?P<instructions>.*)"""


class FileChange(RegexMatchableBaseModel):
    commit_message: str
    code: str
    _regex = r"""Commit Message:(?P<commit_message>.*)<new_file>(python|javascript|typescript|csharp|tsx|jsx)?(?P<code>.*)$"""
    # _regex = r"""Commit Message:(?P<commit_message>.*)(<new_file>|```)(python|javascript|typescript|csharp|tsx|jsx)?(?P<code>.*)($|```)"""

    @classmethod
    def from_string(cls: Type[Self], string: str, **kwargs) -> Self:
        result = super().from_string(string, **kwargs)
        result.code = result.code.strip()
        if result.code.endswith("</new_file>"):
            result.code = result.code[: -len("</new_file>")]
        if len(result.code) == 1:
            result.code = result.code.replace("```", "")
            return result.code + "\n"
        if result.code.startswith("```"):
            first_newline = result.code.find("\n")
            last_newline = result.code.rfind("\n")
            result.code = result.code[first_newline + 1 :]
            result.code = result.code[: last_newline]
        result.code += "\n"
        return result


class PullRequest(RegexMatchableBaseModel):
    title: str
    branch_name: str
    content: str
    _regex = r"""Title:(?P<title>.*)Branch Name:(?P<branch_name>.*)<content>(python|javascript|typescript|csharp|tsx|jsx)?(?P<content>.*)</content>"""


class Snippet(BaseModel):
    """
    Start and end refer to line numbers
    """
    
    content: str
    start: int
    end: int
    file_path: str
    def get_snippet(self):
        snippet = "\n".join(self.content.splitlines()[self.start:self.end])
        if self.start > 1:
            snippet = '...\n' + snippet
        if self.end < self.content.count('\n') + 1:
            snippet = snippet + '\n...'
        return snippet

    def __add__(self, other):
        assert self.content == other.content
        assert self.file_path == other.file_path
        return Snippet(
            content=self.content,
            start=self.start,
            end=other.end,
            file_path=self.file_path
        )
    
    def __xor__(self, other: "Snippet") -> bool:
        """
        Returns True if there is an overlap between two snippets.
        """
        if self.file_path != other.file_path:
            return False
        return self.file_path == other.file_path and (
                (self.start <= other.start and self.end >= other.start)
                or (other.start <= self.start and other.end >= self.start)
            )
        
    def __or__(self, other: "Snippet") -> "Snippet":
        assert self.file_path == other.file_path
        return Snippet(
            content=self.content,
            start=min(self.start, other.start),
            end=max(self.end, other.end),
            file_path=self.file_path
        )
    
    @property
    def xml(self):
        return f"""<snippet filepath="{self.file_path}" start="{self.start}" end="{self.end}">\n{self.get_snippet()}\n</snippet>"""
    
    def get_url(self, repo_name: str, commit_id: str = "main"):
        num_lines = self.content.count("\n") + 1
        return f"https://github.com/{repo_name}/blob/{commit_id}/blob/{self.file_path}#L{max(self.start, 1)}-L{min(self.end, num_lines)}"
    
    def get_markdown_link(self, repo_name: str, commit_id: str = "main"):
        num_lines = self.content.count("\n") + 1
        base = commit_id + "/" if commit_id != "main" else ""
        return f"[{base}{self.file_path}#L{max(self.start, 1)}-L{min(self.end, num_lines)}]({self.get_url(repo_name, commit_id)})"
    
    def get_slack_link(self, repo_name: str, commit_id: str = "main"):
        num_lines = self.content.count("\n") + 1
        base = commit_id + "/" if commit_id != "main" else ""
        return f"<{self.get_url(repo_name, commit_id)}|{base}{self.file_path}#L{max(self.start, 1)}-L{min(self.end, num_lines)}>"

    def get_preview(self, max_lines: int  = 5):
        return "\n".join(self.content.splitlines()[self.start:min(self.start + max_lines, self.end)])

class DiffSummarization(RegexMatchableBaseModel):
    content: str
    _regex = r"""<file_summarization>(?P<content>.*)<\/file_summarization>"""

class PullRequestComment(RegexMatchableBaseModel):
    content: str
    _regex = r"""<review_comment>(?P<content>.*)<\/review_comment>"""