"""Comments on tasks."""

import pytest


def url(task):
    return f"/tasks/{task['id']}/comments"


def test_new_task_has_no_comments(client, team, team_task):
    assert client.get(url(team_task), headers=team.member.headers).json() == []


def test_post_comment_author_comes_from_token(client, team, team_task):
    response = client.post(url(team_task), json={"body": "  Looks good  "}, headers=team.member.headers)

    assert response.status_code == 201
    comment = response.json()
    assert comment["body"] == "Looks good"
    assert comment["task_id"] == team_task["id"]
    assert comment["author"] == {"id": team.member.id, "email": team.member.email}
    assert comment["created_at"]


def test_thread_is_oldest_first_with_each_author(client, team, team_task):
    for account, body in ((team.owner, "first"), (team.member, "second"), (team.admin, "third")):
        client.post(url(team_task), json={"body": body}, headers=account.headers)

    thread = client.get(url(team_task), headers=team.member.headers).json()

    assert [(c["body"], c["author"]["id"]) for c in thread] == [
        ("first", team.owner.id),
        ("second", team.member.id),
        ("third", team.admin.id),
    ]


def test_threads_are_per_task(client, team, team_task):
    other = client.post(
        f"/workspaces/{team.workspace_id}/tasks", json={"title": "other"}, headers=team.owner.headers
    ).json()
    client.post(url(team_task), json={"body": "on the first"}, headers=team.owner.headers)

    assert client.get(url(other), headers=team.owner.headers).json() == []


@pytest.mark.parametrize(
    "body",
    [{}, {"body": ""}, {"body": "   "}, {"body": "x" * 5001}, {"body": "x", "author": {"id": 1}}, {"body": None}],
)
def test_invalid_comment_is_422_and_not_stored(client, team, team_task, body):
    assert client.post(url(team_task), json=body, headers=team.member.headers).status_code == 422
    assert client.get(url(team_task), headers=team.member.headers).json() == []


def test_comment_at_max_length_is_accepted(client, team, team_task):
    assert client.post(url(team_task), json={"body": "x" * 5000}, headers=team.member.headers).status_code == 201


def test_comments_on_missing_task_are_404(client, team):
    missing = {"id": 999_999}
    assert client.get(url(missing), headers=team.owner.headers).status_code == 404
    assert client.post(url(missing), json={"body": "x"}, headers=team.owner.headers).status_code == 404
