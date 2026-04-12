import { Logger, ValidationPipe } from '@nestjs/common';
import { NestFactory } from '@nestjs/core';
import { DocumentBuilder, SwaggerModule } from '@nestjs/swagger';
import { AppModule } from './app.module';
import { RequestNormalizationPipe } from './common/pipes/request-normalization.pipe';

async function bootstrap(): Promise<void> {
  const logger = new Logger('Bootstrap');
  const app = await NestFactory.create(AppModule);

  app.setGlobalPrefix('api', { exclude: ['health'] });
  app.useGlobalPipes(
    new RequestNormalizationPipe(),
    new ValidationPipe({
      whitelist: true,
      forbidNonWhitelisted: true,
      transform: true,
      transformOptions: { enableImplicitConversion: false },
    }),
  );

  app.enableCors({ origin: true, credentials: true });

  const document = SwaggerModule.createDocument(
    app,
    new DocumentBuilder().setTitle('TaskFlow API').setDescription('TaskFlow backend API').setVersion('1.0').addBearerAuth().build(),
  );
  SwaggerModule.setup('api/docs', app, document);

  await app.listen(process.env.PORT || 8080);
  logger.log(`Application is running on port ${process.env.PORT || 8080}`);
}

void bootstrap();
