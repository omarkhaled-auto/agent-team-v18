import { Injectable, Logger, OnModuleDestroy, OnModuleInit } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import Redis from 'ioredis';
import { PrismaService } from '../common/prisma/prisma.service';

export interface AppEvent {
  type: string;
  payload: Record<string, unknown>;
  timestamp: string;
}

type EventHandler = (event: AppEvent) => void | Promise<void>;

@Injectable()
export class EventsService implements OnModuleInit, OnModuleDestroy {
  private readonly logger = new Logger(EventsService.name);
  private publisher: Redis | null = null;
  private subscriber: Redis | null = null;
  private readonly handlers = new Map<string, EventHandler[]>();
  private readonly subscribedChannels = new Set<string>();

  /** Domain handler: updates project timestamp on task events and performs DB writes */
  private readonly taskEventHandler: EventHandler;
  /** Domain handler: soft-deletes tasks when project is archived (DB write) */
  private readonly projectEventHandler: EventHandler;
  /** Domain handler: updates task timestamp when comment is created (DB write) */
  private readonly commentEventHandler: EventHandler;

  constructor(
    private readonly configService: ConfigService,
    private readonly prisma: PrismaService,
  ) {
    // Define domain event handlers that perform real DB writes on domain events.
    // These are bound here so they capture the prisma dependency for business actions.
    this.taskEventHandler = async (event: AppEvent) => {
      if (event.type === 'task.status_changed' || event.type === 'task.created') {
        const { taskId, projectId } = event.payload as { taskId: string; projectId: string };
        await this.prisma.project.update({
          where: { id: projectId },
          data: { updated_at: new Date() },
        });
        this.logger.debug(`Updated project ${projectId} timestamp after task ${taskId} event`);
      }
    };

    this.projectEventHandler = async (event: AppEvent) => {
      if (event.type === 'project.archived') {
        const { projectId } = event.payload as { projectId: string };
        const result = await this.prisma.task.updateMany({
          where: { project_id: projectId, deleted_at: null },
          data: { deleted_at: new Date() },
        });
        this.logger.debug(`Soft-deleted ${result.count} tasks for archived project ${projectId}`);
      }
    };

    this.commentEventHandler = async (event: AppEvent) => {
      if (event.type === 'comment.created') {
        const { taskId } = event.payload as { taskId: string };
        await this.prisma.task.update({
          where: { id: taskId },
          data: { updated_at: new Date() },
        });
        this.logger.debug(`Updated task ${taskId} timestamp after new comment`);
      }
    };

    this.registerHandler('task.events', this.taskEventHandler);
    this.registerHandler('project.events', this.projectEventHandler);
    this.registerHandler('comment.events', this.commentEventHandler);
  }

  async onModuleInit(): Promise<void> {
    const host = this.configService.get<string>('REDIS_HOST', 'localhost');
    const port = Number(this.configService.get<string>('REDIS_PORT', '6379'));

    try {
      this.publisher = new Redis({ host, port, lazyConnect: true, maxRetriesPerRequest: 3 });
      this.subscriber = new Redis({ host, port, lazyConnect: true, maxRetriesPerRequest: 3 });

      await Promise.all([this.publisher.connect(), this.subscriber.connect()]);
      this.subscriber.on('message', (channel: string, message: string) => {
        void this.handleMessage(channel, message);
      });

      await this.subscribeExistingChannels();
      this.logger.log('Redis Pub/Sub connected');
    } catch (error) {
      this.logger.warn(`Redis connection failed; events will be no-ops. ${error instanceof Error ? error.message : String(error)}`);
      this.publisher = null;
      this.subscriber = null;
    }
  }

  async onModuleDestroy(): Promise<void> {
    this.subscriber?.disconnect();
    this.publisher?.disconnect();
    this.subscribedChannels.clear();
  }

  async publish(channel: string, event: Omit<AppEvent, 'timestamp'>): Promise<void> {
    if (!this.publisher) {
      return;
    }

    try {
      await this.publisher.publish(
        channel,
        JSON.stringify({
          ...event,
          timestamp: new Date().toISOString(),
        }),
      );
    } catch (error) {
      this.logger.warn(`Failed to publish event ${event.type} on ${channel}: ${error instanceof Error ? error.message : String(error)}`);
    }
  }

  async subscribe(channel: string, handler: EventHandler): Promise<void> {
    this.registerHandler(channel, handler);
    await this.subscribeChannel(channel);
  }

  private registerHandler(channel: string, handler: EventHandler): void {
    const handlers = this.handlers.get(channel) ?? [];
    handlers.push(handler);
    this.handlers.set(channel, handlers);
  }

  private async subscribeExistingChannels(): Promise<void> {
    await Promise.all([...this.handlers.keys()].map((channel) => this.subscribeChannel(channel)));
  }

  private async subscribeChannel(channel: string): Promise<void> {
    if (!this.subscriber || this.subscribedChannels.has(channel)) {
      return;
    }

    await this.subscriber.subscribe(channel);
    this.subscribedChannels.add(channel);
  }

  private async handleMessage(channel: string, message: string): Promise<void> {
    try {
      const event = JSON.parse(message) as AppEvent;
      const handlers = this.handlers.get(channel) ?? [];
      const results = await Promise.allSettled(handlers.map((handler) => Promise.resolve(handler(event))));

      results.forEach((result) => {
        if (result.status === 'rejected') {
          this.logger.error(
            `Event handler failed on channel ${channel}`,
            result.reason instanceof Error ? result.reason.stack : String(result.reason),
          );
        }
      });
    } catch (error) {
      this.logger.error(`Failed to parse event on channel ${channel}`, error instanceof Error ? error.stack : String(error));
    }
  }
}
