import { Global, Module } from '@nestjs/common';
import { UserRepository } from './user.repository';
import { ProjectRepository } from './project.repository';
import { TaskRepository } from './task.repository';
import { CommentRepository } from './comment.repository';

@Global()
@Module({
  providers: [UserRepository, ProjectRepository, TaskRepository, CommentRepository],
  exports: [UserRepository, ProjectRepository, TaskRepository, CommentRepository],
})
export class RepositoriesModule {}
