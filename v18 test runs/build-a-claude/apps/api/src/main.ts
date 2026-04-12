import { NestFactory } from '@nestjs/core';
import { ValidationPipe } from '@nestjs/common';
import { AppModule } from './app.module';
import { setupSwagger } from './common/swagger.config';
import { ResponseInterceptor } from './common/interceptors/response.interceptor';
import { GlobalExceptionFilter } from './common/filters/http-exception.filter';

async function bootstrap() {
  const app = await NestFactory.create(AppModule);

  // Global prefix
  app.setGlobalPrefix('api', {
    exclude: ['health'],
  });

  // Global validation pipe
  app.useGlobalPipes(
    new ValidationPipe({
      whitelist: true,
      forbidNonWhitelisted: true,
      transform: true,
      transformOptions: {
        enableImplicitConversion: true,
      },
    }),
  );

  // Global response interceptor
  app.useGlobalInterceptors(new ResponseInterceptor());

  // Global exception filter
  app.useGlobalFilters(new GlobalExceptionFilter());

  // Swagger / OpenAPI
  setupSwagger(app);

  // CORS
  app.enableCors({
    origin: true,
    credentials: true,
  });

  const port = process.env.PORT || 8080;
  await app.listen(port);
}

bootstrap();
