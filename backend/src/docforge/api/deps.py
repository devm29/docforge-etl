from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from docforge.container import Container
from docforge.pipeline.queue import JobQueue
from docforge.services.dead_letters import DeadLetterService
from docforge.services.documents import DocumentService
from docforge.services.overview import OverviewService
from docforge.services.reviews import ReviewService
from docforge.services.runs import RunService
from docforge.services.search import SearchService


@dataclass(frozen=True)
class Services:
    container: Container
    queue: JobQueue
    runs: RunService
    documents: DocumentService
    reviews: ReviewService
    search: SearchService
    overview: OverviewService
    dead_letters: DeadLetterService

    @classmethod
    def build(cls, container: Container, queue: JobQueue) -> Services:
        version = container.runner().version
        return cls(
            container=container,
            queue=queue,
            runs=RunService(container.sessions, queue, container.sources, container.exporter, version),
            documents=DocumentService(container.sessions, container.blobs),
            reviews=ReviewService(container.sessions, container.schemas, container.entities),
            search=SearchService(container.sessions, container.embedder),
            overview=OverviewService(container.sessions),
            dead_letters=DeadLetterService(container.sessions, queue, version),
        )


def get_services(request: Request) -> Services:
    services: Services = request.app.state.services
    return services


ServicesDep = Annotated[Services, Depends(get_services)]
